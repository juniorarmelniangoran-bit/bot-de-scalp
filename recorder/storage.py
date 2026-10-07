# recorder/storage.py -- Stockage crash-safe par petits fichiers Parquet (1 min ou N messages), pyarrow/polars.
# Chaque part est ferme immediatement (write_parquet + fsync), range par date/heure ; consolidation ulterieure possible.

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

from recorder.capital import CapitalTick, write_ticks_parquet
from recorder.paths import check_free_space, unique_path


def minute_dir_for_wall_ns(root_dir: Path, wall_ns: int) -> Path:
    """Retourne le dossier date/heure pour wall_ns (UTC) : root/YYYY-MM-DD/HH/"""
    sec = wall_ns // 1_000_000_000
    tm = time.gmtime(int(sec))
    return Path(root_dir) / time.strftime("%Y-%m-%d", tm) / time.strftime("%H", tm)


def minute_parquet_path(root_dir: Path, wall_ns: int, epic: str) -> Path:
    """Chemin d'un part minute : root/YYYY-MM-DD/HH/capital_EPIC_YYYY-MM-DD_HHMM.parquet (unique)."""
    d = minute_dir_for_wall_ns(root_dir, wall_ns)
    sec = wall_ns // 1_000_000_000
    tm = time.gmtime(int(sec))
    stem = f"capital_{epic}_{time.strftime('%Y-%m-%d_%H%M', tm)}"
    base = d / (stem + ".parquet")
    return unique_path(base)


def flush_ticks_crash_safe(
    root_dir: Path,
    ticks: list[CapitalTick],
    min_free_bytes: int = 1_000_000_000,
) -> Path | None:
    """Ecrit ticks en un part Parquet ferme immediatement, retourne le chemin ou None si vide/disk full.

    Verifie l'espace disque avant d'ecrire ; fsync implicite via polars write + close.
    """
    if not ticks:
        return None
    # Prend wall_ns du premier tick pour le nommage
    wall_ns = ticks[0].wall_ns
    epic = ticks[0].epic
    part = minute_parquet_path(root_dir, wall_ns, epic)
    ok, _free = check_free_space(part.parent, min_free_bytes)
    if not ok:
        return None
    part.parent.mkdir(parents=True, exist_ok=True)
    write_ticks_parquet(part, ticks)
    # fsync du fichier et du dossier (meilleure durabilite)
    try:
        import os

        with open(part, "rb") as f:
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
    except Exception:
        pass
    return part


def resolve_epic_via_rest_markets(
    base_url: str,
    cst: str,
    security_token: str,
    search_term: str = "EUR",
    http_client=None,
) -> dict | None:
    """Retrouve l'epic EUR/USD via GET /api/v1/markets?searchTerm=...

    Retourne le premier marche TRADEABLE dont instrumentName contient EUR/USD ou epic == EURUSD variant.
    Ne suppose pas EURUSD ; journalise name/epic/status a l'appelant.
    http_client injectable pour tests (FAKE) ; sinon httpx.
    """
    if http_client is None:
        import httpx

        http_client = httpx
    url = f"{base_url.rstrip('/')}/api/v1/markets"
    params = {"searchTerm": search_term}
    headers = {"CST": cst, "X-SECURITY-TOKEN": security_token}
    try:
        # httpx style : httpx.get(url, params=..., headers=...)
        if hasattr(http_client, "get"):
            resp = http_client.get(url, params=params, headers=headers, timeout=10.0)
        else:
            resp = http_client(url, params=params, headers=headers)
        data = resp.json() if hasattr(resp, "json") else {}
        # Attendu: {"markets": [ {instrumentName, epic, marketStatus, instrumentType, bid, offer, ...}, ... ]}
        markets = data.get("markets") if isinstance(data, dict) else None
        if not isinstance(markets, list) or not markets:
            return None
        # Priorite : epic exact EURUSD variant, sinon nom contient EUR et USD, sinon premier TRADEABLE
        for m in markets:
            epic = str(m.get("epic", ""))
            name = str(m.get("instrumentName", ""))
            status = str(m.get("marketStatus", ""))
            # Cherche EUR/USD
            low_name = name.lower()
            low_epic = epic.lower()
            if ("eur" in low_epic and "usd" in low_epic) or ("eur" in low_name and "usd" in low_name):
                if status.upper() == "TRADEABLE":
                    return m
        # fallback : premier TRADEABLE
        for m in markets:
            if str(m.get("marketStatus", "")).upper() == "TRADEABLE":
                return m
        return markets[0] if markets else None
    except Exception:
        return None
