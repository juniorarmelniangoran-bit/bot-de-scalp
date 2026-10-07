# recorder/paths.py -- Nommage et rotation des fichiers (sans reseau)

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path


def session_dbn_path(out_dir: Path, start_utc: dt.datetime) -> Path:
    """Chemin DBN pour une session : YYYY-MM-DD_HHMMSS.dbn (UTC)."""
    if start_utc.tzinfo is None:
        raise ValueError("start_utc doit etre timezone-aware (UTC)")
    name = start_utc.strftime("%Y-%m-%d_%H%M%S") + ".dbn"
    return Path(out_dir) / name


def unique_path(path: Path) -> Path:
    """Retourne path s'il n'existe pas, sinon path_02, _03... (jamais d'ecrasement)."""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 2
    while True:
        cand = parent / f"{stem}_{i:02d}{suffix}"
        if not cand.exists():
            return cand
        i += 1


def ensure_out_dir(out_dir: Path) -> None:
    Path(out_dir).mkdir(parents=True, exist_ok=True)


def check_free_space(out_dir: Path, min_free_bytes: int) -> tuple[bool, int]:
    """Verifie l'espace disque libre. Retourne (ok, free_bytes). ok=False si < seuil."""
    p = Path(out_dir)
    # shutil.disk_usage marche meme si le dossier n'existe pas encore (on teste le parent)
    anchor = p if p.exists() else p.parent if p.parent.exists() else Path(p.anchor or ".")
    try:
        usage = shutil.disk_usage(anchor)
        free = int(usage.free)
    except (OSError, FileNotFoundError):
        # Si on ne peut pas mesurer, on considere que ce n'est pas ok (arret prudent)
        return False, 0
    return free >= min_free_bytes, free
