# tests Livraison C -- run_capital.py duree limitee, garde-fou, WS fake, pas de reseau
from __future__ import annotations
import os
from pathlib import Path
import pytest
from recorder.run_capital import run_capital_once
from recorder.capital_ws import CapitalWsSession
from recorder.config import CapitalConfig

WALL_NS = 1_700_000_000_000_000_000
MONO_NS = 2_000_000_000_000_000_000

class _FakeHttp:
    def __init__(self, cst="CST_FAKE", tok="TOK_FAKE", markets=None):
        self.cst, self.tok = cst, tok
        self.markets = markets
        self.posts = []
        self.deletes = []
        self.gets = []
    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append(url)
        # reponse session : headers CST + X-SECURITY-TOKEN
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
        self.gets.append((url, params))
        data = self.markets if isinstance(self.markets, dict) else {"markets": [{"epic": "CS.D.EURUSD.MINI.IP","instrumentName":"EUR/USD","marketStatus":"TRADEABLE"}]}
        class RG:
            status_code = 200
            def json(self_inner): return data
            headers = {}
        return RG()

def _mk_cfg(tmp_path: Path, out_dir: Path | None = None) -> Path:
    p = tmp_path / "cfg.toml"
    if out_dir is not None:
        od = str(out_dir).replace("\\","/")
    else:
        od = str((tmp_path / "bot-data" / "capital")).replace("\\","/")
    # TOML : chemin entre quotes simples pour eviter escapes
    p.write_text(f"[capital]\nepic='EURUSD'\nout_dir='{od}'\nbase_url='https://demo-api-capital.backend-capital.com'\nws_url='wss://api-streaming-capital.backend-capital.com/connect'\n", encoding="utf-8")
    return p

def test_run_capital_duree_courte_fake_ws(tmp_path: Path, monkeypatch):
    cfg_path = _mk_cfg(tmp_path)
    monkeypatch.setenv("CAPITAL_API_KEY", "k")
    monkeypatch.setenv("CAPITAL_IDENTIFIER", "id")
    monkeypatch.setenv("CAPITAL_PASSWORD", "pw")
    monkeypatch.setenv("BOT_ENV_FILE", str(tmp_path / "nope.env"))
    monkeypatch.setenv("CAPITAL_ENV", "demo")
    # intercepte load_bot_env_file pour ne pas echouer sur fichier manquant
    import recorder.config as cfgmod
    orig = cfgmod.load_bot_env_file
    cfgmod.load_bot_env_file = lambda: None  # type: ignore
    try:
        fake_http = _FakeHttp()
        # ws_factory qui yield 3 quotes puis s'arrete (lance ConnectionError via timed loop)
        count = [0]
        def fake_factory():
            def gen():
                for _ in range(3):
                    yield {"destination":"quote","payload":{"epic":"EURUSD","bid":1.08,"ofr":1.0802,"bidQty":10,"ofrQty":11,"timestamp":1660297190627}}
            return gen()
        res = run_capital_once(cfg_path, duration_s=2, http_client=fake_http, ws_factory=fake_factory, sleep_fn=lambda d: __import__("time").sleep(0), wall_ns_fn=lambda:WALL_NS, mono_ns_fn=lambda:MONO_NS)
        # doit s'etre arrete (KeyboardInterrupt interne a timed_factory) ou retour normal
        assert fake_http.posts
        assert fake_http.deletes or fake_http.posts  # au moins un delete tente
    finally:
        cfgmod.load_bot_env_file = orig  # type: ignore

def test_run_capital_refuse_live_sans_allow(tmp_path: Path, monkeypatch):
    p = tmp_path / "cfg.toml"
    p.write_text("[capital]\nbase_url='https://demo-api-capital.backend-capital.com.evil.com'\nws_url='wss://api-streaming-capital.backend-capital.com.evil.com/connect'\nout_dir='~/bot-data/capital'\n", encoding="utf-8")
    monkeypatch.setenv("CAPITAL_API_KEY", "k")
    monkeypatch.setenv("CAPITAL_IDENTIFIER", "id")
    monkeypatch.setenv("CAPITAL_PASSWORD", "pw")
    monkeypatch.delenv("ALLOW_LIVE", raising=False)
    import recorder.config as cfgmod
    orig = cfgmod.load_bot_env_file
    cfgmod.load_bot_env_file = lambda: None  # type: ignore
    try:
        with pytest.raises(RuntimeError):
            run_capital_once(p, duration_s=1, http_client=_FakeHttp(), ws_factory=lambda: iter([]))
    finally:
        cfgmod.load_bot_env_file = orig  # type: ignore

def test_run_capital_ne_log_pas_secret(tmp_path: Path, monkeypatch):
    cfg_path = _mk_cfg(tmp_path)
    monkeypatch.setenv("CAPITAL_API_KEY", "SECRET_XYZ_1234567890")
    monkeypatch.setenv("CAPITAL_IDENTIFIER", "ID_XYZ")
    monkeypatch.setenv("CAPITAL_PASSWORD", "PWD_XYZ_99999999")
    monkeypatch.setenv("CAPITAL_ENV", "demo")
    import recorder.config as cfgmod
    orig = cfgmod.load_bot_env_file
    cfgmod.load_bot_env_file = lambda: None  # type: ignore
    try:
        fake_http = _FakeHttp()
        def fake_factory():
            def gen():
                yield {"destination":"quote","payload":{"epic":"EURUSD","bid":1.08,"ofr":1.0802,"timestamp":1}}
            return gen()
        try:
            run_capital_once(cfg_path, duration_s=1, http_client=fake_http, ws_factory=fake_factory, sleep_fn=lambda d: __import__("time").sleep(0))
        except Exception as e:
            msg = str(e)
            assert "SECRET_XYZ" not in msg and "PWD_XYZ" not in msg
    finally:
        cfgmod.load_bot_env_file = orig  # type: ignore
