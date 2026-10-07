"""Garde-fou portabilite : aucun chemin Windows en dur dans recorder/.

Bannit toute lettre de lecteur (ex C:/ , D:[slash]) et la chaine OneDrive dans recorder/*.py
et recorder/*.toml / .env.example. Les URLs https:// et wss:// sont exclues
(elles contiennent :// mais ne sont pas des chemins disque).
BOT_DATA_DIR / CAPITAL_DATA_DIR + Path.home()/bot-data doit etre la seule
source de chemins (via pathlib, portable Linux/Windows).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDER = ROOT / "recorder"

# Lettre de lecteur Windows : ex C:/ ou C:\  (hors URLs https:// / wss://)
DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")
URL_RE = re.compile(r"https?://|wss://", re.IGNORECASE)
# OneDrive interdit dans le code source (hors docs/tests)
ONEDRIVE_RE = re.compile(r"OneDrive", re.IGNORECASE)

# Fichiers a scanner : recorder/*.py + recorder/*.toml + .env.example (racine)
def _strip_urls(line: str) -> str:
    # retire les URLs pour ne pas confondre https:// avec C:/
    return URL_RE.sub("", line)


def _rel(p: Path, base: Path) -> str:
    try:
        return str(p.relative_to(base))
    except ValueError:
        return str(p)


def collect_drive_letter_offenders(root: Path = RECORDER, base: Path = ROOT) -> list[str]:
    root = Path(root)
    base = Path(base)
    offenders: list[str] = []
    # Scanne recursivement tous les .py sous root (recorder/**/*.py)
    for p in root.rglob("*.py"):
        if not p.is_file():
            continue
        if "__pycache__" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = _strip_urls(line)
            if DRIVE_RE.search(stripped):
                offenders.append(f"{_rel(p, base)}:{lineno}: {line.strip()[:220]}")
    # .env.example a la racine du projet (si scan du vrai recorder)
    if root == RECORDER and base == ROOT:
        for p in [base / ".env.example"]:
            if not p.exists():
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if DRIVE_RE.search(_strip_urls(line)):
                    offenders.append(f"{_rel(p, base)}:{lineno}: {line.strip()[:220]}")
    # Quand on scanne un faux dossier tmp/recorder, on scanne aussi son .env.example
    elif base != ROOT:
        fake_env = base / ".env.example"
        if fake_env.exists():
            try:
                text = fake_env.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                text = ""
            for lineno, line in enumerate(text.splitlines(), start=1):
                if DRIVE_RE.search(_strip_urls(line)):
                    offenders.append(f"{_rel(fake_env, base)}:{lineno}: {line.strip()[:220]}")
    # toml recursif sous root (recorder/**/*.toml) -- renforce vs glob top-level seul
    for p in root.rglob("*.toml"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if DRIVE_RE.search(_strip_urls(line)):
                offenders.append(f"{_rel(p, base)}:{lineno}: {line.strip()[:220]}")
    return offenders


def collect_onedrive_offenders(root: Path = RECORDER, base: Path = ROOT) -> list[str]:
    root = Path(root)
    base = Path(base)
    offenders: list[str] = []
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ONEDRIVE_RE.search(line):
                offenders.append(f"{_rel(p, base)}:{lineno}: {line.strip()[:220]}")
    return offenders


def test_no_drive_letter_in_recorder():
    offenders = collect_drive_letter_offenders(RECORDER)
    assert not offenders, (
        "Lettre de lecteur Windows detectee dans recorder/ ou .env.example (interdit : utiliser BOT_DATA_DIR + pathlib, defaut ~/bot-data) :\n"
        + "\n".join(offenders)
        + "\nCorrige : remplace C:/... par Path.home()/\"bot-data\" ou os.environ[\"BOT_DATA_DIR\"] / ..."
    )


def test_no_onedrive_in_recorder():
    offenders = collect_onedrive_offenders(RECORDER)
    assert not offenders, (
        "Chaine 'OneDrive' detectee dans recorder/ (interdit : donnees hors dossier synchro) :\n"
        + "\n".join(offenders)
    )


def test_detector_catches_fake_drive_letter(tmp_path: Path):
    fake = tmp_path / "recorder"
    fake.mkdir()
    # construction dynamique pour ne pas declencher le detecteur sur ce fichier
    drive = "C" + ":/" + "dev/bot-data"
    (fake / "fake.py").write_text(f"x = '{drive}'\n", encoding="utf-8")
    offenders = collect_drive_letter_offenders(fake, tmp_path)
    assert offenders, "Le detecteur de lettre de lecteur n'a rien signale sur un faux C:/"
    assert any("C:/" in o for o in offenders)

    (fake / "fake2.py").write_text("x = 'OneDrive/Documents'\n", encoding="utf-8")
    offenders2 = collect_onedrive_offenders(fake, tmp_path)
    assert offenders2, "Le detecteur OneDrive n'a rien signale"
