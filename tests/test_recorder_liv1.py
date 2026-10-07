"""Livraison 1 : config TOML, nommage/rotation fichiers, espace disque, compagnon, metrics, horloge."""

import datetime as dt
import json
import os
import time
from pathlib import Path

import pytest

from recorder.companion import SecondBucket, append_clock_offset, append_second_line, companion_path_for_dbn
from recorder.config import DEFAULT_OUT_DIR, RecorderConfig, load_config
from recorder.metrics import MinuteAgg, append_minute_line, minute_key_from_wall_ns
from recorder.paths import check_free_space, ensure_out_dir, session_dbn_path, unique_path


def test_config_load_toml(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[recorder]\n'
        'dataset = "GLBX.MDP3"\n'
        'schema = "mbo"\n'
        'stype_in = "continuous"\n'
        'symbols = "6E.c.0"\n'
        'out_dir = "C:\\\\tmp\\\\out"\n'
        'rollover_check_hour_utc = "10:00"\n'
        'min_free_bytes = 123\n'
        'snapshot = true\n',
        encoding="utf-8",
    )
    os.environ.pop("BOT_DATA_DIR", None)
    cfg = load_config(p)
    assert cfg.dataset == "GLBX.MDP3"
    assert cfg.symbols == "6E.c.0"
    assert cfg.min_free_bytes == 123
    assert cfg.snapshot is True


def test_config_bot_data_dir_overrides(tmp_path: Path, monkeypatch):
    p = tmp_path / "config.toml"
    p.write_text('[recorder]\nsymbols="6E.v.0"\n', encoding="utf-8")
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path / "mydata"))
    cfg = load_config(p)
    assert str(cfg.out_dir).replace("\\", "/").endswith("databento/mbo")
    assert str(tmp_path / "mydata") in str(cfg.out_dir)


def test_session_dbn_path_requires_tzaware(tmp_path: Path):
    with pytest.raises(ValueError):
        session_dbn_path(tmp_path, dt.datetime(2026, 10, 5, 14, 3, 2))
    aware = dt.datetime(2026, 10, 5, 14, 3, 2, tzinfo=dt.timezone.utc)
    pp = session_dbn_path(tmp_path, aware)
    assert pp.name == "2026-10-05_140302.dbn"


def test_unique_path_never_overwrites(tmp_path: Path):
    base = tmp_path / "2026-10-05_140302.dbn"
    base.write_text("x", encoding="utf-8")
    p2 = unique_path(base)
    assert p2.name == "2026-10-05_140302_02.dbn"
    p2.write_text("y", encoding="utf-8")
    p3 = unique_path(base)
    assert p3.name == "2026-10-05_140302_03.dbn"


def test_check_free_space_and_ensure_out_dir(tmp_path: Path):
    d = tmp_path / "newdir" / "sub"
    ensure_out_dir(d)
    assert d.exists()
    ok, free = check_free_space(d, 1)
    assert ok is True
    assert free > 0
    ok2, _ = check_free_space(d, 10**18)
    assert ok2 is False


def test_companion_one_line_per_second(tmp_path: Path):
    dbn = tmp_path / "2026-10-05_140302.dbn"
    comp = companion_path_for_dbn(dbn)
    b = SecondBucket()
    b.add(seq=100, ts_recv=1_000_000_000)
    b.add(seq=101, ts_recv=1_000_000_001)
    b.add(seq=102, ts_recv=None)
    wall = time.time_ns()
    mono = time.monotonic_ns()
    append_second_line(comp, wall, mono, b)
    lines = comp.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["count"] == 3
    assert obj["first_seq"] == 100
    assert obj["last_seq"] == 102
    assert obj["wall_ns"] == wall
    assert obj["mono_ns"] == mono


def test_metrics_one_line_per_minute(tmp_path: Path):
    agg = MinuteAgg(minute_key="2026-10-05T14:03:00Z")
    # 2 messages sec 5, 1 message sec 6
    wall = 1_700_000_000_000_000_000
    agg.add(sec=5, seq=10, ts_recv=wall - 5_000_000, wall_ns=wall)
    agg.add(sec=5, seq=11, ts_recv=wall - 2_000_000, wall_ns=wall)
    agg.add(sec=6, seq=12, ts_recv=wall - 1_000_000, wall_ns=wall)
    agg.gaps = 1
    p = tmp_path / "metrics.jsonl"
    append_minute_line(p, agg)
    obj = json.loads(p.read_text(encoding="utf-8").strip())
    assert obj["minute"] == "2026-10-05T14:03:00Z"
    assert obj["messages"] == 3
    assert obj["max_per_second"] == 2
    assert obj["gaps"] == 1
    assert obj["last_seq"] == 12
    assert obj["lag_min_ns"] is not None


def test_minute_key_utc():
    # 2026-10-05 14:03:45 UTC
    dt_aware = dt.datetime(2026, 10, 5, 14, 3, 45, tzinfo=dt.timezone.utc)
    wall_ns = int(dt_aware.timestamp() * 1e9)
    key, sec = minute_key_from_wall_ns(wall_ns)
    assert key == "2026-10-05T14:03:00Z"
    assert sec == 45


def test_clock_offset_file(tmp_path: Path):
    p = tmp_path / "clock_offset.jsonl"
    wall = time.time_ns()
    append_clock_offset(p, wall, 0.002, "time.windows.com")
    obj = json.loads(p.read_text(encoding="utf-8").strip())
    assert obj["server"] == "time.windows.com"
    assert obj["offset_s"] == 0.002
    # None si echec reseau autorise
    append_clock_offset(p, wall, None, "time.windows.com")
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["offset_s"] is None
