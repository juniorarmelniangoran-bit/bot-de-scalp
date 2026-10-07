"""Garde-fou : aucune URL live Capital.com ne doit trainer dans le depot."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "venv", ".venv", "env", "ENV", "data", ".hg"}
LIVE_RE = re.compile("live" + "-" + "api-capital", re.IGNORECASE)


def collect_live_url_offenders(root: Path = ROOT) -> list[str]:
    offenders: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in IGNORED_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in {".py", ".toml", ".md", ".ini", ".txt", ".cfg"} and p.name not in {".env.example"}:
            if p.name != ".env.example":
                continue
        # Ce fichier lui-meme et son jumeau garde-fou sont autorises a mentionner
        # la chaine interdite (ils la bannissent) ; tests/test_capital_recorder y
        # teste le garde-fou hostname exact (evil/live) par construction dynamique.
        if p.resolve() == Path(__file__).resolve():
            continue
        if p.name in {"test_no_live_url.py", "test_capital_recorder.py"}:
            continue
        # docs/ peut citer la chaine interdite pour la bannir dans son historique
        if p.suffix.lower() == ".md":
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if LIVE_RE.search(line):
                offenders.append(f"{p.relative_to(root)}:{lineno}: {line.strip()[:200]}")
    return offenders


def test_no_live_url_in_repo():
    offenders = collect_live_url_offenders(ROOT)
    assert not offenders, ("URL live Capital.com detectee — seul demo-api autorise en Phase 1 :\n" + "\n".join(offenders))


def test_detector_catches_fake_live_url(tmp_path: Path):
    fake = tmp_path / "fake.py"
    fake.write_text("x = 'https://" + "live-api-capital.backend-capital.com'\n", encoding="utf-8")
    offenders = collect_live_url_offenders(tmp_path)
    assert offenders
    assert any("live-api" in o.lower() for o in offenders)
