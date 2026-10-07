"""P2 Capital.com demo : config portable, nommage, rate limiter, Parquet polars, garde-fou ordre."""

import datetime as dt
import os
from pathlib import Path

import pytest

from recorder.capital import (
    DEMO_REST_HOST,
    DEMO_WS_HOST,
    RateLimiter,
    _hostname_of,
    _is_live_url,
    _is_live_ws_url,
    assert_demo_or_allow_live,
    assert_demo_ws_or_allow_live,
    capital_parquet_path,
    companion_path_for_capital,
    gaps_path_for_capital,
    parse_market_snapshot,
    write_ticks_parquet,
    CapitalTick,
)
from recorder.config import load_capital_config, load_config


def test_capital_config_defaults_portable(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CAPITAL_DATA_DIR", raising=False)
    monkeypatch.delenv("BOT_DATA_DIR", raising=False)
    p = tmp_path / "config.toml"
    p.write_text("[capital]\nepic=\"EURUSD\"\n", encoding="utf-8")
    cfg = load_capital_config(p)
    assert cfg.epic == "EURUSD"
    assert "demo-api-capital" in cfg.base_url
    assert cfg.poll_ms == 1000
    assert cfg.rate_limit_per_second == 10
    assert cfg.session_refresh_s == 540
    # Flux prix = WebSocket uniquement (P2) : ws_enabled=True par defaut
    assert cfg.ws_enabled is True
    assert cfg.ws_url == "wss://api-streaming-capital.backend-capital.com/connect"
    assert cfg.ws_max_epics == 40
    assert cfg.ws_ping_interval_s == 300
    # out_dir doit etre sous ~/bot-data/capital (pas C:\ en dur)
    assert "capital" in str(cfg.out_dir).replace("\\", "/")


def test_capital_config_env_overrides(tmp_path: Path, monkeypatch):
    p = tmp_path / "config.toml"
    p.write_text("[capital]\nepic=\"EURUSD\"\n", encoding="utf-8")
    monkeypatch.setenv("CAPITAL_DATA_DIR", str(tmp_path / "my_cap"))
    cfg = load_capital_config(p)
    assert str(tmp_path / "my_cap") in str(cfg.out_dir)


def test_capital_config_fallback_bot_data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CAPITAL_DATA_DIR", raising=False)
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path / "botbase"))
    p = tmp_path / "config.toml"
    p.write_text("[capital]\nepic=\"EURUSD\"\n", encoding="utf-8")
    cfg = load_capital_config(p)
    assert str(tmp_path / "botbase") in str(cfg.out_dir)
    assert "capital" in str(cfg.out_dir).replace("\\", "/")


def test_out_dir_no_hardcoded_c(tmp_path: Path, monkeypatch):
    # Sur Windows Path.home() contient C:\ (normal, via pathlib). On verifie
    # qu'il n'y a pas de "C:\\dev" en dur (ancien defaut non portable) et que
    # la valeur par defaut vient bien de Path.home()/bot-data (portable Linux).
    monkeypatch.delenv("BOT_DATA_DIR", raising=False)
    monkeypatch.delenv("CAPITAL_DATA_DIR", raising=False)
    p = tmp_path / "config.toml"
    p.write_text("[capital]\n", encoding="utf-8")
    cfg = load_capital_config(p)
    assert "C:\\dev" not in str(cfg.out_dir)
    assert "bot-data" in str(cfg.out_dir).replace("\\", "/")
    assert str(Path.home()) in str(cfg.out_dir)
    cfg2 = load_config(p)
    assert "C:\\dev" not in str(cfg2.out_dir)
    assert "bot-data" in str(cfg2.out_dir).replace("\\", "/")


def test_capital_parquet_path_requires_tzaware(tmp_path: Path):
    with pytest.raises(ValueError):
        capital_parquet_path(tmp_path, dt.datetime(2026, 10, 6, 12, 0, 0))
    aware = dt.datetime(2026, 10, 6, 12, 0, 0, tzinfo=dt.timezone.utc)
    pp = capital_parquet_path(tmp_path, aware)
    assert pp.name == "capital_2026-10-06_120000.parquet"
    assert companion_path_for_capital(pp).suffix == ".jsonl"
    assert gaps_path_for_capital(pp).name.endswith(".gaps.jsonl")


def test_rate_limiter_10_per_second():
    rl = RateLimiter(rate_per_second=10)
    t0 = 1000.0
    for _ in range(10):
        assert rl.allow(now_mono=t0) is True
    assert rl.allow(now_mono=t0) is False
    # Fenetre suivante
    assert rl.allow(now_mono=t0 + 1.01) is True


def test_parse_market_snapshot_variants():
    wall, mono = 1_000_000_000, 2_000_000_000
    # Format markets[]
    payload = {"markets": [{"epic": "CS.D.EURUSD.MINI.IP", "bid": 1.08, "offer": 1.0801, "updateTimeUTC": "2026-10-06T12:00:00", "marketStatus": "TRADEABLE"}]}
    tick = parse_market_snapshot(payload, "EURUSD", wall, mono)
    assert tick.bid == 1.08
    assert tick.offer == 1.0801
    assert tick.update_time_utc == "2026-10-06T12:00:00"
    assert tick.status == "TRADEABLE"
    # Format direct bid/offer
    payload2 = {"bid": "1.07", "offer": "1.0702"}
    tick2 = parse_market_snapshot(payload2, "EURUSD", wall, mono)
    assert tick2.bid == 1.07
    assert tick2.offer == 1.0702


def test_write_ticks_parquet_polars(tmp_path: Path):
    ticks = [
        CapitalTick(wall_ns=1, mono_ns=2, epic="EURUSD", bid=1.08, offer=1.0801, update_time_utc="2026-10-06T12:00:00Z"),
        CapitalTick(wall_ns=3, mono_ns=4, epic="EURUSD", bid=1.081, offer=1.0811),
    ]
    out = tmp_path / "capital_2026-10-06_120000.parquet"
    write_ticks_parquet(out, ticks)
    assert out.exists()
    assert out.stat().st_size > 0
    # Lecture via polars
    import polars as pl
    df = pl.read_parquet(out)
    assert len(df) == 2
    assert "wall_ns" in df.columns
    assert "bid" in df.columns
    # Fichier vide
    out2 = tmp_path / "empty.parquet"
    write_ticks_parquet(out2, [])
    assert out2.exists()
    df2 = pl.read_parquet(out2)
    assert len(df2) == 0


def test_assert_demo_or_allow_live():
    # demo OK sans ALLOW_LIVE
    assert_demo_or_allow_live("https://demo-api-capital.backend-capital.com")
    assert_demo_or_allow_live("https://demo-api-capital.backend-capital.com/")
    assert_demo_or_allow_live("https://DEMO-API-CAPITAL.BACKEND-CAPITAL.COM")
    assert_demo_or_allow_live("https://demo-api-capital.backend-capital.com:443")
    # localhost non-capital -> pas bloque (pas une URL capital)
    assert_demo_or_allow_live("http://localhost:8000")
    # live refuse sans ALLOW_LIVE
    with pytest.raises(RuntimeError):
        assert_demo_or_allow_live("https://api-capital.backend-capital.com")
    # evil subdomain qui usurpe demo -> doit etre refuse (hostname exact != demo host)
    with pytest.raises(RuntimeError):
        assert_demo_or_allow_live("https://demo-api-capital.backend-capital.com.evil.com")
    with pytest.raises(RuntimeError):
        assert_demo_or_allow_live("https://live-api-capital.backend-capital.com")
    # live OK avec ALLOW_LIVE=true
    os.environ["ALLOW_LIVE"] = "true"
    try:
        assert_demo_or_allow_live("https://api-capital.backend-capital.com")
        assert_demo_or_allow_live("https://demo-api-capital.backend-capital.com.evil.com")
    finally:
        os.environ.pop("ALLOW_LIVE", None)


def test_demo_guard_hostname_exact():
    # Hostname exact demo -> pas live, meme avec casse/port/slash
    assert _hostname_of("https://demo-api-capital.backend-capital.com") == DEMO_REST_HOST
    assert _hostname_of("https://DEMO-API-CAPITAL.BACKEND-CAPITAL.COM:443/") == DEMO_REST_HOST
    assert _is_live_url("https://demo-api-capital.backend-capital.com") is False
    assert _is_live_url("https://demo-api-capital.backend-capital.com/") is False
    assert _is_live_url("https://demo-api-capital.backend-capital.com:443") is False
    # Evil qui reprend le host demo comme prefixe mais avec suffixe -> live
    assert _is_live_url("https://demo-api-capital.backend-capital.com.evil.com") is True
    assert _is_live_url("https://demo-api-capital.backend-capital.com.evil.com:443/x") is True
    # Autres hosts capital -> live
    assert _is_live_url("https://api-capital.backend-capital.com") is True
    assert _is_live_url("https://live-api-capital.backend-capital.com") is True
    # Non-capital -> pas live (pas de garde-fou capital)
    assert _is_live_url("http://localhost:8000") is False
    assert _is_live_url("") is False
    # WS : meme logique hostname exact
    assert _hostname_of("wss://api-streaming-capital.backend-capital.com/connect") == DEMO_WS_HOST
    assert _is_live_ws_url("wss://api-streaming-capital.backend-capital.com/connect") is False
    assert _is_live_ws_url("wss://api-streaming-capital.backend-capital.com:443/connect") is False
    assert _is_live_ws_url("wss://api-streaming-capital.backend-capital.com.evil.com/connect") is True
    assert _is_live_ws_url("wss://live-api-capital.backend-capital.com/connect") is True
    # WS demo OK sans ALLOW_LIVE, evil/live refuse
    assert_demo_ws_or_allow_live("wss://api-streaming-capital.backend-capital.com/connect")
    with pytest.raises(RuntimeError):
        assert_demo_ws_or_allow_live("wss://api-streaming-capital.backend-capital.com.evil.com/connect")
    os.environ["ALLOW_LIVE"] = "true"
    try:
        assert_demo_ws_or_allow_live("wss://api-streaming-capital.backend-capital.com.evil.com/connect")
    finally:
        os.environ.pop("ALLOW_LIVE", None)
