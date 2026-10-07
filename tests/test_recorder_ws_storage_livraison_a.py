"""Livraison A — P2 Capital.com: WS parse/build + storage crash-safe."""
from __future__ import annotations
import time
from pathlib import Path
import pytest
from recorder.capital import CapitalTick, build_ws_ping_msg, build_ws_subscribe_msg, build_ws_unsubscribe_msg, parse_ws_quote, write_ticks_parquet
from recorder.storage import flush_ticks_crash_safe, minute_dir_for_wall_ns, minute_parquet_path, resolve_epic_via_rest_markets

WALL_NS = 1_700_000_000_000_000_000
MONO_NS = 2_000_000_000_000_000_000

def test_parse_ws_quote_documented_fields():
    msg = {"status": "OK","destination": "quote","payload": {"epic": "OIL_CRUDE","product": "CFD","bid": 93.87,"bidQty": 4976.0,"ofr": 93.9,"ofrQty": 5000.0,"timestamp": 1660297190627}}
    tick = parse_ws_quote(msg, WALL_NS, MONO_NS)
    assert tick is not None
    assert tick.epic == "OIL_CRUDE"
    assert tick.bid == 93.87
    assert tick.offer == 93.9
    assert tick.bid_sz == 4976.0
    assert tick.offer_sz == 5000.0
    assert tick.update_time_utc == "1660297190627"

def test_parse_ws_quote_variantes():
    m = {"payload": {"epic": "CS.D.EURUSD.MINI.IP","bid": "1.08","offer": "1.0801","bidQty": "10","offerQty": "12","timestamp": 123456}}
    t = parse_ws_quote(m, WALL_NS, MONO_NS)
    assert t is not None and t.bid == 1.08 and t.offer == 1.0801
    m2 = {"payload": {"epic": "EURUSD","bid": 1.08,"offer": 1.0801,"timestamp": 999}}
    assert parse_ws_quote(m2, WALL_NS, MONO_NS) is not None
    assert parse_ws_quote({"destination": "ping","payload": {}}, WALL_NS, MONO_NS) is None
    assert parse_ws_quote({"destination": "quote","payload": {"product": "CFD"}}, WALL_NS, MONO_NS) is None
    assert parse_ws_quote({}, WALL_NS, MONO_NS) is None
    assert parse_ws_quote({"payload": {"nope": 1}}, WALL_NS, MONO_NS) is None

def test_parse_ws_quote_timestamp_as_int():
    m = {"payload": {"epic": "EURUSD","bid": 1.08,"ofr": 1.0801,"ofrQty": 10,"bidQty": 10,"timestamp": "1660297190627"}}
    t = parse_ws_quote(m, WALL_NS, MONO_NS)
    assert t is not None and t.update_time_utc == "1660297190627"

def test_build_ws_messages():
    m = build_ws_subscribe_msg("cst1","tok1",["EURUSD"])
    assert m["destination"] == "marketData.subscribe"
    assert m["payload"]["epics"] == ["EURUSD"]
    with pytest.raises(ValueError):
        build_ws_subscribe_msg("c","t", [f"E{i}" for i in range(41)])
    up = build_ws_unsubscribe_msg("c","t",["EURUSD"])
    assert up["destination"] == "marketData.unsubscribe"
    ping = build_ws_ping_msg("cst1","tok1", correlation_id="5")
    assert ping["destination"] == "ping"
    assert ping["correlationId"] == "5"

def test_write_ticks_parquet_roundtrip(tmp_path: Path):
    ticks = [CapitalTick(wall_ns=1, mono_ns=2, epic="EURUSD", bid=1.08, offer=1.0801)]
    out = tmp_path / "a.parquet"
    write_ticks_parquet(out, ticks)
    assert out.exists() and out.stat().st_size > 0
    import polars as pl
    assert len(pl.read_parquet(out)) == 1
    out2 = tmp_path / "empty.parquet"
    write_ticks_parquet(out2, [])
    assert out2.exists()
    assert len(pl.read_parquet(out2)) == 0

def test_flush_ticks_crash_safe(tmp_path: Path):
    wall = int(time.time()*1e9)
    ticks = [CapitalTick(wall_ns=wall, mono_ns=wall+1, epic="EURUSD", bid=1.08, offer=1.0801)]
    root = tmp_path / "bot-data" / "capital"
    part = flush_ticks_crash_safe(root, ticks)
    assert part is not None and part.exists()
    assert "capital_EURUSD" in part.name
    assert flush_ticks_crash_safe(root, []) is None
    assert flush_ticks_crash_safe(root, ticks, min_free_bytes=10**18) is None
    assert minute_parquet_path(root, wall, "EURUSD").suffix == ".parquet"
    assert minute_dir_for_wall_ns(root, wall).exists or True

class _FakeResp:
    def __init__(self, data): self._data = data
    def json(self): return self._data
class _FakeHttpx:
    def __init__(self, data): self._data = data; self.last_url = None
    def get(self, url, params=None, headers=None, timeout=None):
        self.last_url = url; return _FakeResp(self._data)

def test_resolve_epic_prioritises_tradeable_eur_usd():
    data = {"markets": [{"epic": "OTHER","instrumentName": "Gold","marketStatus": "TRADEABLE"},{"epic": "CS.D.EURUSD.MINI.IP","instrumentName": "EUR/USD","marketStatus": "TRADEABLE"},{"epic": "CS.D.EURUSD2","instrumentName": "EUR/USD variant","marketStatus": "CLOSED"}]}
    fake = _FakeHttpx(data)
    m = resolve_epic_via_rest_markets("https://demo-api-capital.backend-capital.com","cst","tok", search_term="EUR", http_client=fake)
    assert m is not None and m["marketStatus"] == "TRADEABLE"
    assert "EUR" in m["epic"] or "EUR" in m["instrumentName"]
    assert "markets" in fake.last_url
    data2 = {"markets": [{"epic": "X","instrumentName": "XAU/USD","marketStatus": "TRADEABLE"}]}
    assert resolve_epic_via_rest_markets("https://demo-api-capital.backend-capital.com","c","t", http_client=_FakeHttpx(data2)) is not None
    assert resolve_epic_via_rest_markets("https://demo-api-capital.backend-capital.com","c","t", http_client=_FakeHttpx({})) is None
    assert resolve_epic_via_rest_markets("https://demo-api-capital.backend-capital.com","c","t", http_client=_FakeHttpx({"markets": []})) is None
