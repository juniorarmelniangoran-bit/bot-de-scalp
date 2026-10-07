# recorder/capital.py -- Enregistreur Capital.com DEMO (Phase 1)
# Aucune fonction d'ordre ici. Demo par defaut, ALLOW_LIVE requis pour live.
# Docs cites https://open-api.capital.com/ :
#   REST base demo https://demo-api-capital.backend-capital.com
#     POST /api/v1/session, DELETE /api/v1/session, GET /api/v1/ping, GET /api/v1/time
#     GET /api/v1/markets?searchTerm=...&epics=...  (retrouve l'epic EUR/USD, ne suppose pas EURUSD)
#     GET /api/v1/markets/{epic} (controle ponctuel seulement ; prix temps reel = WebSocket)
#   WebSocket (SEULE source prix haute frequence) :
#     wss://api-streaming-capital.backend-capital.com/connect
#     destination marketData.subscribe / marketData.unsubscribe, max 40 epics
#     request: {"destination":"marketData.subscribe","correlationId":"1","cst":...,"securityToken":...,"payload":{"epics":["OIL_CRUDE"]}}
#     quote:   {"status":"OK","destination":"quote","payload":{"epic":"OIL_CRUDE","product":"CFD","bid":93.87,"bidQty":4976.0,"ofr":93.9,"ofrQty":5000.0,"timestamp":1660297190627}}
#              (champs exacts doc: epic, product, bid, bidQty, ofr, ofrQty, timestamp ms)
#     ping WS: {"destination":"ping","correlationId":"5","cst":...,"securityToken":...} -> {"status":"OK","destination":"ping",...}
#              doc: "In order to keep the connection alive, ping service at least once every 10 minutes."
#              On ping a 300s (5 min, marge < 10 min).
# Session 10 min ("Session is active for 10 minutes"), limite 10 req/s (CLAUDE.md s4).

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path


# Constantes demo (comparaison exacte du hostname, pas substring)
DEMO_REST_HOST = "demo-api-capital.backend-capital.com"
DEMO_WS_HOST = "api-streaming-capital.backend-capital.com"
# Live si hostname != DEMO_REST_HOST mais host finit par capital (garde-fou reel)
# On compare le hostname exact (urllib.parse), pas un substring ("demo-api" in url
# laisserait passer demo-api-capital.backend-capital.com.evil.com).


def _hostname_of(url: str) -> str:
    """Extrait le hostname normalise (minuscule, sans port) depuis une URL."""
    from urllib.parse import urlparse

    try:
        h = urlparse(url).hostname or ""
    except Exception:
        h = ""
    return h.lower().strip()


def _is_live_url(base_url: str) -> bool:
    """True si base_url pointe vers un host live (non-demo).

    Regle : REST live si hostname != DEMO_REST_HOST et qu'il contient
    "capital" (evite les faux positifs sur une URL vide/localhost en test).
    WS live detecte separement via _is_live_ws_url.
    Cas piege bloque : demo-api-capital.backend-capital.com.evil.com
    -> hostname = demo-api-capital.backend-capital.com.evil.com != DEMO_REST_HOST
    -> live (refuse sans ALLOW_LIVE).
    """
    host = _hostname_of(base_url)
    if not host:
        return False
    # host demo exact -> jamais live
    if host == DEMO_REST_HOST:
        return False
    # tout autre host contenant "capital" ou "api-capital" est considere live
    # (y compris sous-domaine evil qui usurpe le suffixe)
    return "capital" in host


def _is_live_ws_url(ws_url: str) -> bool:
    """True si ws_url ne pointe pas exactement vers DEMO_WS_HOST."""
    host = _hostname_of(ws_url)
    if not host:
        return False
    if host == DEMO_WS_HOST:
        return False
    return "capital" in host


def assert_demo_or_allow_live(base_url: str) -> None:
    if _is_live_url(base_url) and os.environ.get("ALLOW_LIVE", "").lower() != "true":
        raise RuntimeError(
            "Base URL live refusee : ALLOW_LIVE=true + Phase 4 requis (CLAUDE.md s6)."
        )


def assert_demo_ws_or_allow_live(ws_url: str) -> None:
    if _is_live_ws_url(ws_url) and os.environ.get("ALLOW_LIVE", "").lower() != "true":
        raise RuntimeError(
            "WS URL live refusee : ALLOW_LIVE=true + Phase 4 requis (CLAUDE.md s6)."
        )


def capital_parquet_path(out_dir: Path, start_utc: dt.datetime) -> Path:
    if start_utc.tzinfo is None:
        raise ValueError("start_utc timezone-aware UTC requis")
    return Path(out_dir) / ("capital_" + start_utc.strftime("%Y-%m-%d_%H%M%S") + ".parquet")


def companion_path_for_capital(parquet_path: Path) -> Path:
    return parquet_path.with_suffix("").parent / (parquet_path.stem + ".recv.jsonl")


def metrics_path_for_capital(parquet_path: Path) -> Path:
    return parquet_path.with_suffix("").parent / (parquet_path.stem + ".metrics.jsonl")


def gaps_path_for_capital(parquet_path: Path) -> Path:
    return parquet_path.with_suffix("").parent / (parquet_path.stem + ".gaps.jsonl")


def clock_offset_path_for_capital(parquet_path: Path) -> Path:
    return parquet_path.with_suffix("").parent / (parquet_path.stem + ".clock_offset.jsonl")


@dataclass
class RateLimiter:
    rate_per_second: int = 10
    _window_start_mono: float = field(default=0.0, init=False, repr=False)
    _count_in_window: int = field(default=0, init=False, repr=False)

    def allow(self, now_mono: float | None = None) -> bool:
        now = time.monotonic() if now_mono is None else now_mono
        if now - self._window_start_mono >= 1.0:
            self._window_start_mono = now
            self._count_in_window = 0
        if self._count_in_window < self.rate_per_second:
            self._count_in_window += 1
            return True
        return False

    def seconds_until_next_window(self, now_mono: float | None = None) -> float:
        now = time.monotonic() if now_mono is None else now_mono
        return max(0.0, 1.0 - (now - self._window_start_mono))


@dataclass(frozen=True)
class CapitalTick:
    wall_ns: int
    mono_ns: int
    epic: str
    bid: float | None
    offer: float | None
    bid_sz: float | None = None
    offer_sz: float | None = None
    update_time_utc: str | None = None
    status: str | None = None

    def to_dict(self) -> dict:
        return {
            "wall_ns": self.wall_ns,
            "mono_ns": self.mono_ns,
            "epic": self.epic,
            "bid": self.bid,
            "offer": self.offer,
            "bid_sz": self.bid_sz,
            "offer_sz": self.offer_sz,
            "update_time_utc": self.update_time_utc,
            "status": self.status,
        }


def parse_market_snapshot(payload: dict, epic: str, wall_ns: int, mono_ns: int) -> CapitalTick:
    src: dict = payload
    if "markets" in payload and isinstance(payload["markets"], list) and payload["markets"]:
        src = payload["markets"][0]
    elif "snapshot" in payload and isinstance(payload["snapshot"], dict):
        src = payload["snapshot"]
    bid = src.get("bid")
    offer = src.get("offer")
    bid_sz = src.get("bidQty") if "bidQty" in src else src.get("bid_sz")
    offer_sz = src.get("offerQty") if "offerQty" in src else src.get("offer_sz")
    update_time_utc = src.get("updateTimeUTC") or src.get("updateTime")
    status = src.get("marketStatus") or src.get("status")
    try:
        bid_f = float(bid) if bid is not None else None
    except Exception:
        bid_f = None
    try:
        offer_f = float(offer) if offer is not None else None
    except Exception:
        offer_f = None
    return CapitalTick(
        wall_ns=wall_ns, mono_ns=mono_ns,
        epic=str(src.get("epic", epic)),
        bid=bid_f, offer=offer_f,
        bid_sz=float(bid_sz) if bid_sz is not None else None,
        offer_sz=float(offer_sz) if offer_sz is not None else None,
        update_time_utc=str(update_time_utc) if update_time_utc is not None else None,
        status=str(status) if status is not None else None,
    )


def parse_ws_quote(payload: dict, wall_ns: int, mono_ns: int) -> CapitalTick | None:
    """Parse un message WebSocket quote -> CapitalTick ou None si non-quote / mal forme.

    Horodatage local wall_ns/mono_ns : a passer IMMEDIATEMENT a la reception,
    avant tout traitement (exigence P2 #2).
    Payload doc: {"epic":"OIL_CRUDE","product":"CFD","bid":93.87,"bidQty":4976.0,"ofr":93.9,"ofrQty":5000.0,"timestamp":1660297190627}
    """
    # Le quote est dans payload si destination=="quote" (ou directement payload selon lib)
    inner = payload
    # Si enveloppe {destination, payload: {epic,...}}
    if "payload" in payload and isinstance(payload["payload"], dict) and payload.get("destination") == "quote":
        inner = payload["payload"]
    elif "payload" in payload and isinstance(payload["payload"], dict) and "epic" in payload["payload"]:
        # enveloppe sans destination mais avec payload
        inner = payload["payload"]
    if "epic" not in inner or "bid" not in inner:
        return None
    # champs exacts doc : bid, bidQty, ofr/ofrQty (doc utilise "ofr"), timestamp ms
    try:
        bid = float(inner["bid"]) if inner.get("bid") is not None else None
    except Exception:
        bid = None
    try:
        # doc dit "ofr" (pas offer)
        ofr = inner.get("ofr", inner.get("offer"))
        offer = float(ofr) if ofr is not None else None
    except Exception:
        offer = None
    try:
        bid_qty = inner.get("bidQty", inner.get("bid_sz"))
        bid_sz = float(bid_qty) if bid_qty is not None else None
    except Exception:
        bid_sz = None
    try:
        ofr_qty = inner.get("ofrQty", inner.get("offerQty", inner.get("offer_sz")))
        ofr_sz = float(ofr_qty) if ofr_qty is not None else None
    except Exception:
        ofr_sz = None
    ts_ms = inner.get("timestamp")
    try:
        ts_ms_i = int(ts_ms) if ts_ms is not None else None
    except Exception:
        ts_ms_i = None
    # wall_ns/mono_ns deja fournis par l'appelant (prises a la reception)
    return CapitalTick(
        wall_ns=wall_ns,
        mono_ns=mono_ns,
        epic=str(inner.get("epic", "")),
        bid=bid,
        offer=offer,
        bid_sz=bid_sz,
        offer_sz=ofr_sz,
        update_time_utc=str(ts_ms_i) if ts_ms_i is not None else None,
        status=str(inner.get("product", "")) or None,
    )


def build_ws_subscribe_msg(cst: str, security_token: str, epics: list[str], correlation_id: str = "1") -> dict:
    """Construit le JSON de souscription WS marketData.subscribe.

    Doc : {"destination":"marketData.subscribe","correlationId":"1","cst":"...","securityToken":"...","payload":{"epics":["OIL_CRUDE"]}}
    """
    if len(epics) > 40:
        raise ValueError("max 40 epics (doc WebSocket)")
    return {
        "destination": "marketData.subscribe",
        "correlationId": correlation_id,
        "cst": cst,
        "securityToken": security_token,
        "payload": {"epics": list(epics)},
    }


def build_ws_unsubscribe_msg(cst: str, security_token: str, epics: list[str], correlation_id: str = "2") -> dict:
    return {
        "destination": "marketData.unsubscribe",
        "correlationId": correlation_id,
        "cst": cst,
        "securityToken": security_token,
        "payload": {"epics": list(epics)},
    }


def build_ws_ping_msg(cst: str, security_token: str, correlation_id: str = "5") -> dict:
    """Ping WS : doc 'ping service at least once every 10 minutes'."""
    return {
        "destination": "ping",
        "correlationId": correlation_id,
        "cst": cst,
        "securityToken": security_token,
    }


def write_ticks_parquet(path: Path, ticks: list[CapitalTick]) -> None:
    import polars as pl

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if not ticks:
        df = pl.DataFrame(
            {
                "wall_ns": pl.Series([], dtype=pl.Int64),
                "mono_ns": pl.Series([], dtype=pl.Int64),
                "epic": pl.Series([], dtype=pl.Utf8),
                "bid": pl.Series([], dtype=pl.Float64),
                "offer": pl.Series([], dtype=pl.Float64),
            }
        )
        df.write_parquet(path)
        return
    df = pl.DataFrame([t.to_dict() for t in ticks])
    df.write_parquet(path)


def append_gap_line(path: Path, wall_ns: int, reason: str, last_wall_ns: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"wall_ns": wall_ns, "last_wall_ns": last_wall_ns, "reason": reason}) + "\n")


def password_hash_for_log(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()[:12]

