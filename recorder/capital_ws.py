# recorder/capital_ws.py -- Livraison B : WS Capital.com testable, FAKE injectable, zero reseau
# ws_backoff_seconds / is_retryable_http_status / should_send_ws_ping sont purs et testes sans reseau.
# CapitalWsSession centralise garde-fou hostname exact, parsing, ping 300s, rate limit 10/s, flush crash-safe.

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

class DureeAtteinte(Exception):
    """Fin normale de duree --duration atteinte (pas un Ctrl+C).

    Levee par _make_real_ws_factory (recv timeout reveil periodique) ou par
    timed_factory dans run_capital.py. Le resume doit afficher interrupted=False,
    a la difference de KeyboardInterrupt (vrai Ctrl+C -> interrupted=True).
    """

    pass


from recorder.capital import (
    CapitalTick,
    RateLimiter,
    assert_demo_or_allow_live,
    assert_demo_ws_or_allow_live,
    build_ws_ping_msg,
    build_ws_subscribe_msg,
    build_ws_unsubscribe_msg,
    parse_ws_quote,
)
from recorder.config import CapitalConfig
from recorder.storage import flush_ticks_crash_safe


def ws_backoff_seconds(attempt: int, base_s: float = 1.0, cap_s: float = 60.0) -> float:
    if attempt < 0:
        attempt = 0
    delay = base_s * (2**attempt)
    return min(delay, cap_s)


def is_retryable_http_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599


def should_send_ws_ping(elapsed_s: float, interval_s: int = 300) -> bool:
    return elapsed_s >= float(interval_s)


def run_ws_reconnect_loop(
    session: "CapitalWsSession",
    ws_factory,
    *,
    sleep_fn=None,
    max_attempts: int | None = None,
    wall_ns_fn=None,
    mono_ns_fn=None,
) -> dict:
    """Boucle connexion/reconnexion WS testable (FAKE injectable, zero reseau).

    ws_factory : callable -> iterable de payloads dict (ou leve).
    A chaque deconnexion (exception hors KeyboardInterrupt) : disconnects++,
    flush crash-safe, backoff expo cap 60s via ws_backoff_seconds, sleep_fn(delay).
    Ping 300s gere via session.need_ping/build_ping/mark_ping_sent si ws_sender dispo.
    KeyboardInterrupt : flush+unsubscribe+DELETE via session.shutdown() puis propage
    (arret propre sans add_signal_handler ; le caller peut catcher).
    Retourne dict resume. Ne fait aucun appel reseau reel ; tout I/O est injecte.
    """
    if sleep_fn is None:
        sleep_fn = time.sleep
    if wall_ns_fn is None:
        wall_ns_fn = lambda: time.time_ns()
    if mono_ns_fn is None:
        mono_ns_fn = lambda: time.monotonic_ns()
    attempt = 0
    # last_ping init si None : on le pose maintenant pour que need_ping devienne actif apres 300s
    if session.last_ping_mono is None:
        try:
            session.last_ping_mono = session.clock_mono() if session.clock_mono else time.monotonic()  # type: ignore
        except Exception:
            session.last_ping_mono = 0.0
    while True:
        if max_attempts is not None and attempt > max_attempts:
            try:
                session.shutdown()
            except Exception:
                pass
            return {"attempts": attempt, "disconnects": session.disconnects, "interrupted": False}
        try:
            iterable = ws_factory()
            # ws_factory peut lever directement (connexion echouee)
            # iterate payloads
            for payload in iterable:
                # ping periodique
                try:
                    if session.need_ping():
                        msg = session.build_ping()
                        sender = session.ws_sender
                        if sender is not None:
                            try:
                                sender(msg)
                            except Exception:
                                pass
                        session.mark_ping_sent()
                except Exception:
                    pass
                wall_ns = wall_ns_fn()
                mono_ns = mono_ns_fn()
                try:
                    session.handle_message(payload, wall_ns, mono_ns)
                except Exception:
                    pass
            # fin normale de l'iterable = deconnexion serveur (doit reconnecter)
            raise ConnectionError("ws closed by server")
        except DureeAtteinte:
            # fin normale de duree : flush + unsubscribe + DELETE puis propage DureeAtteinte
            # (distingue de KeyboardInterrupt -> interrupted=False vs True)
            try:
                session.shutdown()
            except Exception:
                pass
            raise
        except KeyboardInterrupt:
            # arret propre demande utilisateur (Ctrl-C) : flush + unsubscribe + DELETE
            try:
                session.shutdown()
            except Exception:
                pass
            raise
        except BaseException as e:
            # BaseException inclut DureeAtteinte/KeyboardInterrupt deja geres, SystemExit etc
            if isinstance(e, SystemExit):
                raise
            # toute autre exception = deconnexion a retenter
            session.disconnects += 1
            try:
                session.flush()
            except Exception:
                pass
            delay = ws_backoff_seconds(attempt)
            try:
                sleep_fn(delay)
            except (KeyboardInterrupt, DureeAtteinte):
                try:
                    session.shutdown()
                except Exception:
                    pass
                raise
            except Exception:
                pass
            attempt += 1
            continue


@dataclass
class CapitalWsSession:
    """Etat WS testable. Tout I/O injecte (FAKE en tests) : ws_sender, http_client, clock_mono."""

    config: CapitalConfig
    cst: str
    security_token: str
    epics: list[str]
    out_dir: Path | None = None
    ws_sender: Callable[[dict], None] | None = None
    http_client: object | None = None
    clock_mono: Callable[[], float] | None = None

    ticks: list[CapitalTick] = field(default_factory=list, init=False)
    malformed_count: int = field(default=0, init=False)
    ping_count: int = field(default=0, init=False)
    ping_recv_count: int = field(default=0, init=False)
    disconnects: int = field(default=0, init=False)
    last_ping_mono: float | None = field(default=None, init=False)
    _rate_limiter: RateLimiter = field(init=False)

    def __post_init__(self) -> None:
        assert_demo_or_allow_live(self.config.base_url)
        assert_demo_ws_or_allow_live(self.config.ws_url)
        if len(self.epics) > self.config.ws_max_epics:
            raise ValueError(f"max {self.config.ws_max_epics} epics")
        if self.out_dir is None:
            self.out_dir = self.config.out_dir
        self._rate_limiter = RateLimiter(rate_per_second=self.config.rate_limit_per_second)
        if self.clock_mono is None:
            self.clock_mono = time.monotonic

    def handle_message(self, payload: dict, wall_ns: int, mono_ns: int) -> CapitalTick | None:
        """ping -> ignore (compte ping_recv), quote -> tick, sinon malforme++ (ne leve jamais)."""
        try:
            if isinstance(payload, dict) and payload.get("destination") == "ping":
                self.ping_recv_count += 1
                return None
            tick = parse_ws_quote(payload, wall_ns, mono_ns)
            if tick is None:
                self.malformed_count += 1
                return None
            self.ticks.append(tick)
            return tick
        except Exception:
            self.malformed_count += 1
            return None

    def need_ping(self, now_mono: float | None = None) -> bool:
        if self.last_ping_mono is None:
            return False
        now = self.clock_mono() if now_mono is None else now_mono  # type: ignore[misc]
        return should_send_ws_ping(now - self.last_ping_mono, self.config.ws_ping_interval_s)

    def build_ping(self, correlation_id: str = "5") -> dict:
        self.ping_count += 1
        return build_ws_ping_msg(self.cst, self.security_token, correlation_id)

    def mark_ping_sent(self, now_mono: float | None = None) -> None:
        now = self.clock_mono() if now_mono is None else now_mono  # type: ignore[misc]
        self.last_ping_mono = now

    def subscribe_msg(self) -> dict:
        return build_ws_subscribe_msg(self.cst, self.security_token, self.epics)

    def unsubscribe_msg(self) -> dict:
        return build_ws_unsubscribe_msg(self.cst, self.security_token, self.epics)

    def should_retry_http(self, status: int) -> bool:
        return is_retryable_http_status(status)

    def backoff_seconds(self, attempt: int) -> float:
        return ws_backoff_seconds(attempt)

    def allow_request(self, now_mono: float | None = None) -> bool:
        return self._rate_limiter.allow(now_mono=now_mono)

    def flush(self) -> Path | None:
        if not self.ticks:
            return None
        assert self.out_dir is not None
        part = flush_ticks_crash_safe(self.out_dir, self.ticks, min_free_bytes=self.config.min_free_bytes)
        if part is not None:
            self.ticks = []
        return part

    def shutdown(
        self,
        ws_send: Callable[[dict], None] | None = None,
        http_delete: Callable[[], object] | None = None,
    ) -> dict:
        """Flush + unsubscribe + DELETE session. Ne leve jamais, FAKE injectable."""
        flushed: Path | None = None
        try:
            flushed = self.flush()
        except Exception:
            flushed = None
        sender = ws_send if ws_send is not None else self.ws_sender
        if sender is not None:
            try:
                sender(self.unsubscribe_msg())
            except Exception:
                pass
        deleter = http_delete
        if deleter is None and self.http_client is not None:
            def _default_delete() -> object | None:
                try:
                    hc = self.http_client  # type: ignore[assignment]
                    if hasattr(hc, "delete"):
                        url = f"{self.config.base_url.rstrip('/')}/api/v1/session"
                        headers = {"CST": self.cst, "X-SECURITY-TOKEN": self.security_token}
                        return hc.delete(url, headers=headers, timeout=10.0)  # type: ignore[attr-defined]
                except Exception:
                    return None
                return None
            deleter = _default_delete
        if deleter is not None:
            try:
                deleter()
            except Exception:
                pass
        return {
            "flushed": str(flushed) if flushed is not None else None,
            "pending_ticks": len(self.ticks),
            "malformed": self.malformed_count,
            "pings": self.ping_count,
            "disconnects": self.disconnects,
        }
