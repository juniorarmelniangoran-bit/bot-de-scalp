# tests etape 1 -- timeout WebSocket + respect duree + DureeAtteinte vs KeyboardInterrupt
# 1) arret dans les 3 s apres --duration avec faux WS qui leve TimeoutError en continu
# 2) ping 300 s sans aucun message recu
from __future__ import annotations
import time
import json as _json
from pathlib import Path
import pytest
from recorder.capital_ws import CapitalWsSession, DureeAtteinte
from recorder.config import CapitalConfig
from recorder.run_capital import _make_real_ws_factory, run_capital_once

WALL_NS = 1_700_000_000_000_000_000
MONO_NS = 2_000_000_000_000_000_000


class _FakeHttp:
    def __init__(self, cst="CST_FAKE", tok="TOK_FAKE"):
        self.cst, self.tok = cst, tok
        self.posts = []
        self.deletes = []
    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append(url)
        class R:
            status_code = 200
            headers = {"CST": self.cst, "X-SECURITY-TOKEN": self.tok}
            def json(self_inner): return {}
        return R()
    def delete(self, url, headers=None, timeout=None):
        self.deletes.append(url)
        class RD:
            status_code = 200
            headers = {}
            def json(self_inner): return {}
        return RD()
    def get(self, url, params=None, headers=None, timeout=None):
        class RG:
            status_code = 200
            headers = {}
            def json(self_inner): return {"markets": [{"epic": "CS.D.EURUSD.MINI.IP", "instrumentName": "EUR/USD", "marketStatus": "TRADEABLE"}]}
        return RG()


def _mk_cfg(tmp_path: Path) -> Path:
    p = tmp_path / "cfg.toml"
    od = str((tmp_path / "bot-data" / "capital")).replace("\\", "/")
    p.write_text(f"[capital]\nepic='EURUSD'\nout_dir='{od}'\nbase_url='https://demo-api-capital.backend-capital.com'\nws_url='wss://api-streaming-capital.backend-capital.com/connect'\nws_ping_interval_s=300\n", encoding="utf-8")
    return p


class _FakeWsTimeout:
    """Faux ws : recv(timeout) leve toujours TimeoutError, send enregistre."""
    def __init__(self):
        self.sent: list[str] = []
        self.recv_calls = 0
    def send(self, data: str):
        self.sent.append(data)
    def recv(self, timeout=None):
        self.recv_calls += 1
        raise TimeoutError("fake recv timeout")
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class _FakeConnectCtx:
    def __init__(self, fake_ws):
        self._ws = fake_ws
    def __enter__(self):
        return self._ws
    def __exit__(self, *a):
        return False


def test_arret_dans_3s_apres_duration_fake_ws_timeout_continu(tmp_path: Path, monkeypatch):
    """Preuve duree : meme si recv leve TimeoutError en continu (serveur muet),
    _make_real_ws_factory s'arrete dans les 3 s apres --duration via DureeAtteinte."""
    cfg = CapitalConfig(ws_url="wss://api-streaming-capital.backend-capital.com/connect", ws_ping_interval_s=300)
    session = CapitalWsSession(config=cfg, cst="CST_F", security_token="TOK_F", epics=["EURUSD"], out_dir=tmp_path)
    session.clock_mono = time.monotonic  # type: ignore
    fake_ws = _FakeWsTimeout()
    def fake_connect(*a, **kw):
        assert kw.get("open_timeout") == 10
        assert kw.get("close_timeout") == 5
        return _FakeConnectCtx(fake_ws)
    monkeypatch.setattr("websockets.sync.client.connect", fake_connect)
    duration_s = 2
    start = time.monotonic()
    deadline = start + duration_s
    deadline_fn = lambda: time.monotonic() >= deadline
    factory = _make_real_ws_factory(cfg, "CST_F", "TOK_F", ["EURUSD"], session, recv_timeout_s=0.05, deadline_fn=deadline_fn)
    gen = factory()
    t0 = time.monotonic()
    with pytest.raises(DureeAtteinte):
        for _ in gen:
            pass
    elapsed = time.monotonic() - t0
    total = time.monotonic() - start
    assert total < duration_s + 3.0, f"trop lent : total={total:.2f}s attendu < {duration_s+3}s (recv bloquant ?)"
    assert fake_ws.recv_calls >= 2


def test_ping_300s_sans_aucun_message_recu(tmp_path: Path, monkeypatch):
    """Preuve ping : meme sans quote (recv TimeoutError continu), ping destination=ping part apres intervalle.
    Sans le ping 300 s dans le bloc TimeoutError, ce test echoue car 0 quote => 0 ping."""
    cfg = CapitalConfig(ws_url="wss://api-streaming-capital.backend-capital.com/connect", ws_ping_interval_s=1)
    session = CapitalWsSession(config=cfg, cst="CST_F", security_token="TOK_F", epics=["EURUSD"], out_dir=tmp_path)
    session.clock_mono = time.monotonic  # type: ignore
    session.last_ping_mono = time.monotonic() - 5
    fake_ws = _FakeWsTimeout()
    def fake_connect(*a, **kw):
        return _FakeConnectCtx(fake_ws)
    monkeypatch.setattr("websockets.sync.client.connect", fake_connect)
    # deadline 2 s > intervalle 1 s : laisse le temps au ping de partir puis coupe proprement via DureeAtteinte
    deadline = time.monotonic() + 2
    deadline_fn = lambda: time.monotonic() >= deadline
    factory = _make_real_ws_factory(cfg, "CST_F", "TOK_F", ["EURUSD"], session, recv_timeout_s=0.05, deadline_fn=deadline_fn)
    gen = factory()
    with pytest.raises(DureeAtteinte):
        for _ in gen:
            pass  # aucune quote n'est yield, on boucle sur TimeoutError -> ping
    pings = [m for m in fake_ws.sent if "ping" in m]
    assert len(pings) >= 1, f"aucun ping envoye sans message recu, sent={fake_ws.sent}"
    found = False
    for raw in pings:
        try:
            obj = _json.loads(raw)
            if obj.get("destination") == "ping":
                found = True
        except Exception:
            pass
    assert found, f"ping mal forme : {pings}"
    assert session.ping_count >= 1


def test_duree_atteinte_vs_keyboardinterrupt_interrupted_flag(tmp_path: Path, monkeypatch):
    """DureeAtteinte -> interrupted False (fin normale), KeyboardInterrupt -> interrupted True (Ctrl-C)."""
    cfg_path = _mk_cfg(tmp_path)
    monkeypatch.setenv("CAPITAL_API_KEY", "k")
    monkeypatch.setenv("CAPITAL_IDENTIFIER", "id")
    monkeypatch.setenv("CAPITAL_PASSWORD", "pw")
    monkeypatch.setenv("BOT_ENV_FILE", str(tmp_path / "nope.env"))
    monkeypatch.setenv("CAPITAL_ENV", "demo")
    import recorder.config as cfgmod
    orig = cfgmod.load_bot_env_file
    cfgmod.load_bot_env_file = lambda: None  # type: ignore
    try:
        fake_http = _FakeHttp()
        def factory_duree():
            def gen():
                if True:
                    raise DureeAtteinte("duree atteinte test")
                yield {}
            return gen()
        res = run_capital_once(cfg_path, duration_s=1, http_client=fake_http, ws_factory=factory_duree, sleep_fn=lambda d: time.sleep(0), wall_ns_fn=lambda: WALL_NS, mono_ns_fn=lambda: MONO_NS)
        assert res.get("interrupted") is False, f"DureeAtteinte doit donner interrupted False, got {res}"
        assert res.get("duree_atteinte") is True
        def factory_kb():
            def gen():
                if True:
                    raise KeyboardInterrupt("ctrl c test")
                yield {}
            return gen()
        fake_http2 = _FakeHttp()
        res2 = run_capital_once(cfg_path, duration_s=1, http_client=fake_http2, ws_factory=factory_kb, sleep_fn=lambda d: time.sleep(0), wall_ns_fn=lambda: WALL_NS, mono_ns_fn=lambda: MONO_NS)
        assert res2.get("interrupted") is True, f"KeyboardInterrupt doit donner interrupted True, got {res2}"
    finally:
        cfgmod.load_bot_env_file = orig  # type: ignore

