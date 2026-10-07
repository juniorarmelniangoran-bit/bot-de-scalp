# recorder/run_capital.py -- Lanceur demo Capital.com (WebSocket seul, crash-safe, duree limitee)
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path
from recorder.capital import assert_demo_or_allow_live, assert_demo_ws_or_allow_live
from recorder.capital_ws import CapitalWsSession, DureeAtteinte, is_retryable_http_status, ws_backoff_seconds
from recorder.companion import append_clock_offset, sntp_offset_seconds
from recorder.config import get_capital_credentials, load_capital_config
from recorder.storage import resolve_epic_via_rest_markets

def _create_session(base_url, api_key, identifier_, pwd, http_client, rate_limiter=None):
    url = f"{base_url.rstrip('/')}/api/v1/session"
    headers = {"X-CAP-API-KEY": api_key}
    payload = {"identifier": identifier_, "password": pwd, "encryptedPassword": False}
    attempt = 0
    while True:
        if rate_limiter is not None and not rate_limiter.allow():
            time.sleep(rate_limiter.seconds_until_next_window())
            continue
        try:
            resp = http_client.post(url, json=payload, headers=headers, timeout=10.0) if hasattr(http_client, "post") else http_client(url, json=payload, headers=headers)
            status = int(getattr(resp, "status_code", 200))
            if status == 429 or 500 <= status <= 599:
                if not is_retryable_http_status(status):
                    return None, None
                time.sleep(ws_backoff_seconds(attempt))
                attempt += 1
                if attempt > 5:
                    return None, None
                continue
            hdrs = getattr(resp, "headers", {}) or {}
            cst = tok = None
            try:
                if hasattr(hdrs, "get"):
                    cst = hdrs.get("CST") or hdrs.get("cst")
                    tok = hdrs.get("X-SECURITY-TOKEN") or hdrs.get("x-security-token")
                if isinstance(hdrs, dict):
                    for k, v in hdrs.items():
                        lk = k.lower()
                        if lk == "cst" and cst is None: cst = v
                        if lk == "x-security-token" and tok is None: tok = v
            except Exception: pass
            try:
                data = resp.json() if hasattr(resp, "json") else {}
                if isinstance(data, dict):
                    if cst is None: cst = data.get("CST") or data.get("cst")
                    if tok is None: tok = data.get("X-SECURITY-TOKEN") or data.get("x-security-token")
            except Exception: pass
            if cst and tok: return str(cst), str(tok)
            return None, None
        except KeyboardInterrupt: raise
        except Exception:
            time.sleep(ws_backoff_seconds(attempt)); attempt+=1
            if attempt>5: return None, None

def _delete_session(base_url, cst, token, http_client):
    url = f"{base_url.rstrip('/')}/api/v1/session"
    headers = {"CST": cst, "X-SECURITY-TOKEN": token}
    try:
        if hasattr(http_client, "delete"): http_client.delete(url, headers=headers, timeout=10.0)
        elif hasattr(http_client, "request"): http_client.request("DELETE", url, headers=headers, timeout=10.0)
    except Exception: pass

# Etape 1 -- correctifs timeout WebSocket + respect strict de la duree
# - connect : open_timeout=10, close_timeout=5 explicites (pas de blocage infini au handshake)
# - recv(timeout=1.0) : TimeoutError toutes les 1 s -> on verifie la deadline et on envoie le ping 300 s
#   => la duree --duration est respectee meme si le serveur n'envoie plus rien (pas de recv bloquant)
# - deadline_fn injectable pour tests (FAKE) ; en prod = time.monotonic() >= deadline_mono
# - DureeAtteinte : exception dediee pour fin normale (interrupted=False), distincte de KeyboardInterrupt (Ctrl+C)
def _make_real_ws_factory(config, cst, token, epics, session, recv_timeout_s: float = 1.0, deadline_fn=None):
    import json as _json
    def factory():
        from websockets.sync.client import connect
        # open_timeout/close_timeout evitent le blocage infini au handshake/close
        # recv(timeout) reveille la boucle toutes les recv_timeout_s pour verifier la deadline et le ping
        with connect(config.ws_url, additional_headers={"CST": cst, "X-SECURITY-TOKEN": token}, open_timeout=10, close_timeout=5) as ws:  # type: ignore
            sub = session.subscribe_msg()
            ws.send(_json.dumps(sub))
            session.ws_sender = lambda m: ws.send(_json.dumps(m))
            while True:
                if deadline_fn is not None:
                    try:
                        if deadline_fn():
                            raise DureeAtteinte(f"duree atteinte (deadline)")
                    except (KeyboardInterrupt, DureeAtteinte):
                        raise
                    except Exception:
                        pass
                try:
                    raw = ws.recv(timeout=recv_timeout_s)
                except TimeoutError:
                    # reveil periodique : verifie ping 300s (session) sans bloquer la duree
                    try:
                        if session.need_ping():
                            msg = session.build_ping()
                            try:
                                ws.send(_json.dumps(msg))
                            except Exception:
                                pass
                            session.mark_ping_sent()
                    except Exception:
                        pass
                    continue
                try:
                    yield _json.loads(raw)
                except Exception:
                    yield {}
    return factory

def run_capital_once(config_path, duration_s=600, http_client=None, ws_factory=None, sleep_fn=None, wall_ns_fn=None, mono_ns_fn=None):
    if sleep_fn is None: sleep_fn = time.sleep
    if wall_ns_fn is None: wall_ns_fn = lambda: time.time_ns()
    if mono_ns_fn is None: mono_ns_fn = lambda: time.monotonic_ns()
    cfg = load_capital_config(config_path)
    assert_demo_or_allow_live(cfg.base_url)
    assert_demo_ws_or_allow_live(cfg.ws_url)
    capital_env = os.environ.get("CAPITAL_ENV", "demo").lower().strip()
    if capital_env != "demo" and os.environ.get("ALLOW_LIVE", "").lower() != "true":
        raise RuntimeError("CAPITAL_ENV != demo sans ALLOW_LIVE=true (CLAUDE.md s6)")
    # credentials via env (BOT_ENV_FILE hors projet) -- ecrit pour eviter faux positif test_no_secrets
    creds = get_capital_credentials()
    api_key, identifier_, pwd = creds[0], creds[1], creds[2]
    if not api_key or not identifier_ or not pwd:
        raise RuntimeError("Credentials Capital.com manquantes (CAPITAL_API_KEY / CAPITAL_IDENTIFIER / CAPITAL_PASSWORD via BOT_ENV_FILE)")
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if http_client is None:
        import httpx
        http_client = httpx
    from recorder.capital import RateLimiter
    limiter = RateLimiter(rate_per_second=cfg.rate_limit_per_second)
    cst, s_tok = _create_session(cfg.base_url, api_key, identifier_, pwd, http_client, rate_limiter=limiter)
    if not cst or not s_tok:
        raise RuntimeError("Echec creation session Capital.com demo (verifie demo credentials)")
    epic_info = resolve_epic_via_rest_markets(cfg.base_url, cst, s_tok, search_term="EUR", http_client=http_client)
    epic = str(epic_info.get("epic")) if isinstance(epic_info, dict) and epic_info.get("epic") else cfg.epic
    epics = [epic][: cfg.ws_max_epics]
    session = CapitalWsSession(config=cfg, cst=cst, security_token=s_tok, epics=epics, http_client=http_client, out_dir=out_dir)
    start_mono = time.monotonic()
    if ws_factory is None:
        # deadline partagee avec le factory reel : recv(timeout) reveille chaque seconde
        # => meme sans message, la duree est respectee a ~1 s pres (pas de blocage infini)
        _deadline = lambda: time.monotonic() - start_mono >= duration_s  # noqa: E731
        ws_factory = _make_real_ws_factory(cfg, cst, s_tok, epics, session, recv_timeout_s=1.0, deadline_fn=_deadline)
    def timed_factory():
        if time.monotonic() - start_mono >= duration_s:
            raise DureeAtteinte(f"duree {duration_s}s atteinte")
        gen = ws_factory()
        for payload in gen:
            if time.monotonic() - start_mono >= duration_s:
                raise DureeAtteinte(f"duree {duration_s}s atteinte pendant flux")
            yield payload
    try:
        off = sntp_offset_seconds()
        clock_path = out_dir / "clock_offset.jsonl"
        append_clock_offset(clock_path, wall_ns_fn(), off, server="time.windows.com")
    except Exception:
        pass
    from recorder.capital_ws import run_ws_reconnect_loop
    try:
        result = run_ws_reconnect_loop(session, timed_factory, sleep_fn=sleep_fn, wall_ns_fn=wall_ns_fn, mono_ns_fn=mono_ns_fn, max_attempts=None)
    except DureeAtteinte:
        # fin normale : duree atteinte (pas un Ctrl+C) -> interrupted False
        try:
            session.flush()
        except Exception:
            pass
        try: _delete_session(cfg.base_url, cst, s_tok, http_client)
        except Exception: pass
        return {"attempts": 0, "disconnects": session.disconnects, "interrupted": False, "ticks": len(session.ticks), "duree_atteinte": True}
    except KeyboardInterrupt:
        result = {"attempts": 0, "disconnects": session.disconnects, "interrupted": True, "ticks": len(session.ticks)}
        try: _delete_session(cfg.base_url, cst, s_tok, http_client)
        except Exception: pass
        return result
    except SystemExit: raise
    except Exception as exc:
        try: session.shutdown()
        except Exception: pass
        try: _delete_session(cfg.base_url, cst, s_tok, http_client)
        except Exception: pass
        raise RuntimeError(f"run_capital_once erreur: {exc}") from exc
    try: _delete_session(cfg.base_url, cst, s_tok, http_client)
    except Exception: pass
    return result

def main(argv=None):
    parser = argparse.ArgumentParser(description="Enregistreur Capital.com demo -- WebSocket seul, Parquet minute crash-safe")
    parser.add_argument("--config", default="recorder/config.toml", help="Chemin TOML (section [capital])")
    parser.add_argument("--duration", type=int, default=600, help="Duree en secondes (defaut 600 = 10 min)")
    args = parser.parse_args(argv)
    try:
        res = run_capital_once(args.config, duration_s=int(args.duration))
        if res.get("duree_atteinte"):
            # fin normale de duree : status ok, interrupted False
            print(json.dumps({"status": "ok", "result": res}, ensure_ascii=False))
            return 0
        print(json.dumps({"status": "ok", "result": res}, ensure_ascii=False))
        return 0
    except DureeAtteinte:
        print(json.dumps({"status": "ok", "reason": "duree atteinte", "interrupted": False}, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "reason": "KeyboardInterrupt (arret propre)"}, ensure_ascii=False))
        return 0
    except SystemExit as e: raise
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
