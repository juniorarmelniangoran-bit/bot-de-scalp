"""Livraison B -- faux serveur : WS testable sans reseau reel."""

from __future__ import annotations

from pathlib import Path

import pytest

from recorder.capital_ws import (
    CapitalWsSession,
    is_retryable_http_status,
    run_ws_reconnect_loop,
    should_send_ws_ping,
    ws_backoff_seconds,
)
from recorder.config import CapitalConfig

WALL_NS = 1_700_000_000_000_000_000
MONO_NS = 2_000_000_000_000_000_000


def _demo_cfg(tmp_path: Path | None = None, **overrides) -> CapitalConfig:
    base = dict(
        epic="EURUSD",
        base_url="https://demo-api-capital.backend-capital.com",
        out_dir=Path(tmp_path) if tmp_path is not None else Path.home() / "bot-data" / "capital",
        ws_url="wss://api-streaming-capital.backend-capital.com/connect",
        ws_ping_interval_s=300,
        ws_max_epics=40,
    )
    base.update(overrides)
    return CapitalConfig(**base)  # type: ignore[arg-type]


def test_ws_backoff_expo():
    assert ws_backoff_seconds(0) == 1.0
    assert ws_backoff_seconds(1) == 2.0
    assert ws_backoff_seconds(3) == 8.0
    assert ws_backoff_seconds(10) == 60.0
    assert ws_backoff_seconds(100) == 60.0
    assert ws_backoff_seconds(-1) == 1.0


def test_retryable_status():
    assert is_retryable_http_status(429) is True
    assert is_retryable_http_status(500) is True
    assert is_retryable_http_status(599) is True
    assert is_retryable_http_status(200) is False
    assert is_retryable_http_status(400) is False


def test_ping_300s():
    assert should_send_ws_ping(299, 300) is False
    assert should_send_ws_ping(300, 300) is True
    assert should_send_ws_ping(600, 300) is True


def test_handle_malformed_ignored(tmp_path: Path):
    cfg = _demo_cfg(tmp_path / "out")
    sess = CapitalWsSession(config=cfg, cst="cst1", security_token="tok1", epics=["EURUSD"])
    assert sess.handle_message({"destination": "ping"}, WALL_NS, MONO_NS) is None
    assert sess.malformed_count == 0
    assert sess.handle_message({}, WALL_NS, MONO_NS) is None
    assert sess.malformed_count == 1
    assert sess.handle_message({"destination": "quote", "payload": {}}, WALL_NS, MONO_NS) is None
    assert sess.malformed_count == 2
    ok = {"destination": "quote", "payload": {"epic": "EURUSD", "bid": 1.08, "ofr": 1.0802, "bidQty": 10, "ofrQty": 11, "timestamp": 1660297190627}}
    t = sess.handle_message(ok, WALL_NS, MONO_NS)
    assert t is not None and t.bid == 1.08 and t.offer == 1.0802
    assert len(sess.ticks) == 1
    assert sess.malformed_count == 2


def test_ping_need_and_build(tmp_path: Path):
    mono = [0.0]
    cfg = _demo_cfg(tmp_path / "out", ws_ping_interval_s=300)
    sess = CapitalWsSession(config=cfg, cst="c", security_token="t", epics=["EURUSD"], clock_mono=lambda: mono[0])
    sess.last_ping_mono = 0.0
    assert sess.need_ping() is False
    mono[0] = 299.0
    assert sess.need_ping() is False
    mono[0] = 300.0
    assert sess.need_ping() is True
    msg = sess.build_ping()
    assert msg["destination"] == "ping"
    assert sess.ping_count == 1
    sess.mark_ping_sent()
    assert sess.last_ping_mono == 300.0
    assert sess.need_ping() is False
    mono[0] = 600.0
    assert sess.need_ping() is True


def test_flush_and_disk_full(tmp_path: Path):
    cfg = _demo_cfg(tmp_path / "out")
    sess = CapitalWsSession(config=cfg, cst="c", security_token="t", epics=["EURUSD"])
    assert sess.flush() is None
    ok = {"destination": "quote", "payload": {"epic": "EURUSD", "bid": 1.08, "ofr": 1.0802, "timestamp": 1}}
    sess.handle_message(ok, WALL_NS, MONO_NS)
    part = sess.flush()
    assert part is not None and part.exists()
    assert len(sess.ticks) == 0
    cfg_full = _demo_cfg(tmp_path / "out2", min_free_bytes=10**18)
    sess2 = CapitalWsSession(config=cfg_full, cst="c", security_token="t", epics=["EURUSD"])
    sess2.handle_message(ok, WALL_NS, MONO_NS)
    assert sess2.flush() is None
    assert len(sess2.ticks) == 1


def test_shutdown_flush_unsubscribe_delete(tmp_path: Path):
    cfg = _demo_cfg(tmp_path / "out")
    sent: list[dict] = []
    deleted: list[str] = []

    class _FakeHttp:
        def delete(self, url, headers=None, timeout=None):
            deleted.append(url)
            return None

    sess = CapitalWsSession(config=cfg, cst="cst1", security_token="tok1", epics=["EURUSD"], ws_sender=lambda m: sent.append(m), http_client=_FakeHttp())
    ok = {"destination": "quote", "payload": {"epic": "EURUSD", "bid": 1.08, "ofr": 1.0802, "timestamp": 1}}
    sess.handle_message(ok, WALL_NS, MONO_NS)
    resumo = sess.shutdown()
    assert resumo["flushed"] is not None
    assert len(sess.ticks) == 0
    assert sent and sent[0]["destination"] == "marketData.unsubscribe"
    assert deleted and "session" in deleted[0]
    sent2: list[dict] = []
    deleted2: list[str] = []
    sess2 = CapitalWsSession(config=cfg, cst="c", security_token="t", epics=["EURUSD"])
    sess2.shutdown(ws_send=lambda m: sent2.append(m), http_delete=lambda: deleted2.append("del"))
    assert sent2 and sent2[0]["destination"] == "marketData.unsubscribe"
    assert deleted2 == ["del"]


def test_guards_demo_and_max_epics():
    cfg_ok = _demo_cfg()
    sess = CapitalWsSession(config=cfg_ok, cst="c", security_token="t", epics=["EURUSD"])
    assert sess.epics == ["EURUSD"]
    cfg_bad_ws = _demo_cfg(ws_url="wss://api-streaming-capital.backend-capital.com.evil.com/connect")
    with pytest.raises(RuntimeError):
        CapitalWsSession(config=cfg_bad_ws, cst="c", security_token="t", epics=["EURUSD"])
    cfg_bad_rest = _demo_cfg(base_url="https://api-capital.backend-capital.com")
    with pytest.raises(RuntimeError):
        CapitalWsSession(config=cfg_bad_rest, cst="c", security_token="t", epics=["EURUSD"])
    with pytest.raises(ValueError):
        CapitalWsSession(config=cfg_ok, cst="c", security_token="t", epics=[f"E{i}" for i in range(41)])


def test_rate_limiter_and_backoff():
    cfg = _demo_cfg(rate_limit_per_second=2)
    sess = CapitalWsSession(config=cfg, cst="c", security_token="t", epics=["EURUSD"])
    assert sess.allow_request(now_mono=0.0) is True
    assert sess.allow_request(now_mono=0.0) is True
    assert sess.allow_request(now_mono=0.0) is False
    assert sess.allow_request(now_mono=1.1) is True
    assert sess.should_retry_http(429) is True
    assert sess.should_retry_http(500) is True
    assert sess.should_retry_http(200) is False
    assert sess.backoff_seconds(0) == 1.0
    assert sess.backoff_seconds(10) == 60.0


def test_ws_reconnect_loop_faux_serveur_coupe(tmp_path: Path):
    """Faux serveur qui coupe : le loop reconnecte avec backoff expo, flush et compte disconnects."""
    cfg = _demo_cfg(tmp_path / "out_reconnect")
    sent: list[dict] = []
    sleeps: list[float] = []
    calls = [0]

    def fake_factory():
        calls[0] += 1
        if calls[0] == 1:
            # premiere connexion : envoie 1 quote puis coupe (leve)
            def gen1():
                yield {"destination": "quote", "payload": {"epic": "EURUSD", "bid": 1.08, "ofr": 1.0802, "timestamp": 1}}
                raise ConnectionError("faux cut 1")
            return gen1()
        if calls[0] == 2:
            def gen2():
                yield {"destination": "quote", "payload": {"epic": "EURUSD", "bid": 1.09, "ofr": 1.0902, "timestamp": 2}}
                raise RuntimeError("faux cut 2")
            return gen2()
        # 3eme appel : on arrete le test via limite attempts
        def gen3():
            raise ConnectionError("cut 3")
            yield  # type: ignore
        return gen3()

    sess = CapitalWsSession(config=cfg, cst="c", security_token="t", epics=["EURUSD"], ws_sender=lambda m: sent.append(m), clock_mono=lambda: 0.0)
    # on ne teste pas le ping ici, juste la reconnexion
    res = run_ws_reconnect_loop(
        sess,
        fake_factory,
        sleep_fn=lambda d: sleeps.append(d),
        max_attempts=2,
        wall_ns_fn=lambda: WALL_NS,
        mono_ns_fn=lambda: MONO_NS,
    )
    # gen3 leve immediatement -> 3e disconnect, puis attempt=3 > max 2 -> return
    assert sess.disconnects == 3
    assert calls[0] == 3
    assert sleeps == [1.0, 2.0, 4.0]
    assert res["disconnects"] == 3
    assert res["attempts"] == 3


def test_ws_reconnect_keyboardinterrupt_arret_propre(tmp_path: Path):
    """KeyboardInterrupt (Ctrl-C) : flush + unsubscribe + DELETE puis propage -- sans add_signal_handler."""
    cfg = _demo_cfg(tmp_path / "out_kb")
    sent: list[dict] = []
    deleted: list[str] = []

    class _FakeHttp:
        def delete(self, url, headers=None, timeout=None):
            deleted.append(url)
            return None

    def raising_sleep(_delay: float):
        raise KeyboardInterrupt("ctrl-c pendant backoff")

    # factory qui coupe immediatement -> loop fait sleep -> KeyboardInterrupt
    def fake_factory():
        def gen():
            yield {"destination": "quote", "payload": {"epic": "EURUSD", "bid": 1.08, "ofr": 1.0802, "timestamp": 1}}
            raise ConnectionError("cut -> backoff -> ctrl-c")
        return gen()

    sess = CapitalWsSession(config=cfg, cst="c", security_token="t", epics=["EURUSD"], ws_sender=lambda m: sent.append(m), http_client=_FakeHttp(), clock_mono=lambda: 0.0)
    try:
        run_ws_reconnect_loop(sess, fake_factory, sleep_fn=raising_sleep, wall_ns_fn=lambda: WALL_NS, mono_ns_fn=lambda: MONO_NS)
        assert False, "KeyboardInterrupt attendu"
    except KeyboardInterrupt:
        pass
    # shutdown a du flusher et envoyer unsubscribe + DELETE meme sur KeyboardInterrupt
    assert any(m.get("destination") == "marketData.unsubscribe" for m in sent)
    assert deleted and "session" in deleted[0]
    # ticks vides apres flush reussi (disque ok)
    assert len(sess.ticks) == 0

    # Variante : KeyboardInterrupt leve directement depuis ws_factory (pendant iteration)
    sent2: list[dict] = []
    deleted2: list[str] = []

    class _FakeHttp2:
        def delete(self, url, headers=None, timeout=None):
            deleted2.append(url)
            return None

    def factory_kb_direct():
        def gen():
            yield {"destination": "quote", "payload": {"epic": "EURUSD", "bid": 1.08, "ofr": 1.0802, "timestamp": 1}}
            raise KeyboardInterrupt("ctrl-c in gen")
        return gen()

    sess2 = CapitalWsSession(config=cfg, cst="c", security_token="t", epics=["EURUSD"], ws_sender=lambda m: sent2.append(m), http_client=_FakeHttp2(), clock_mono=lambda: 0.0)
    try:
        run_ws_reconnect_loop(sess2, factory_kb_direct, sleep_fn=lambda d: None, wall_ns_fn=lambda: WALL_NS, mono_ns_fn=lambda: MONO_NS)
        assert False, "KeyboardInterrupt attendu (direct)"
    except KeyboardInterrupt:
        pass
    assert any(m.get("destination") == "marketData.unsubscribe" for m in sent2)
    assert deleted2 and "session" in deleted2[0]
