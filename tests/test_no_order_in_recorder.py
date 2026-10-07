"""
Garde-fou : le dossier recorder/ ne doit contenir aucun appel de passage d'ordre.

Raison : en Phase 1, le recorder enregistre seulement les flux (Databento + Capital.com).
Aucun ordre ne doit etre envoye (CLAUDE.md section 6).
Endpoints d'ordre verifies sur https://open-api.capital.com/ et listes dans ORDER_PATTERNS ci-dessous.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDER_DIR = ROOT / "recorder"

# Endpoints Capital.com verifies sur https://open-api.capital.com/ (2026-10-06) :
#   POST /api/v1/positions  (Create position)  ; PUT /api/v1/positions/{dealId} ; DELETE /api/v1/positions/{dealId}
#   POST /api/v1/workingorders (Create working order) ; PUT/DELETE /api/v1/workingorders/{dealId}
#   POST /api/v1/positions/otq  (quote) si present ; tout POST/PUT/DELETE vers /positions ou /workingorders = ordre
#   Garde-fou : tout POST vers ces endpoints dans recorder/ doit echouer.
ORDER_PATTERNS = [
    # Termes generiques d'execution (toujours interdits en recorder/)
    re.compile(r"\bcreate_order\b", re.IGNORECASE),
    re.compile(r"\bplace_order\b", re.IGNORECASE),
    re.compile(r"\bsend_order\b", re.IGNORECASE),
    re.compile(r"\bopen_position\b", re.IGNORECASE),
    re.compile(r"\bclose_position\b", re.IGNORECASE),
    # Endpoints REST d'ordre Capital.com verifies (doc https://open-api.capital.com/)
    re.compile(r"POST\s+[^\n]*?/positions\b", re.IGNORECASE),
    re.compile(r"POST\s+[^\n]*?/workingorders\b", re.IGNORECASE),
    re.compile(r"PUT\s+[^\n]*?/positions/\{", re.IGNORECASE),
    re.compile(r"DELETE\s+[^\n]*?/positions/\{", re.IGNORECASE),
    re.compile(r"PUT\s+[^\n]*?/workingorders/\{", re.IGNORECASE),
    re.compile(r"DELETE\s+[^\n]*?/workingorders/\{", re.IGNORECASE),
    # Filet large : toute reference codee a /api/v1/positions ou /api/v1/workingorders en POST/PUT/DELETE
    re.compile(r"/api/v1/(positions|workingorders)\b.*\b(POST|PUT|DELETE)\b", re.IGNORECASE),
    re.compile(r"\b(POST|PUT|DELETE)\b.*\/api\/v1\/(positions|workingorders)\b", re.IGNORECASE),
    re.compile(r"\b(positions|workingorders)\b.*\b(POST|PUT|DELETE)\b", re.IGNORECASE),
    # httpx/requests vers ces URLs avec methode d'ecriture
    re.compile(r"httpx\.(post|put|delete)\s*\([^)]*positions", re.IGNORECASE),
    re.compile(r"httpx\.(post|put|delete)\s*\([^)]*workingorders", re.IGNORECASE),
]

IGNORED_DIRS = {"__pycache__", ".pytest_cache"}
ALLOWED_EXTS = {".py"}


def collect_order_offenders(root: Path = RECORDER_DIR, base: Path = ROOT) -> list[str]:
    """Scanne root (defaut recorder/) et retourne les lignes suspectes.

    Fonction publique et testable : accepte un dossier racine en parametre
    pour pouvoir etre verifiee sur un dossier temporaire.
    """
    offenders: list[str] = []
    root = Path(root)
    base = Path(base)
    if not root.exists():
        return offenders
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in ALLOWED_EXTS:
            continue
        if any(part in IGNORED_DIRS for part in p.parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in ORDER_PATTERNS:
                if pat.search(line):
                    try:
                        rel = p.relative_to(base)
                    except ValueError:
                        rel = p
                    offenders.append(
                        f"{rel}:{lineno}: motif `{pat.pattern}` trouve dans: {line.strip()}"
                    )
                    break
    return offenders


def test_no_order_in_recorder():
    """Echoue si un motif de passage d'ordre est trouve dans recorder/."""
    offenders = collect_order_offenders(RECORDER_DIR, ROOT)
    assert not offenders, (
        "Appel(s) de passage d'ordre detecte(s) dans recorder/ (interdit en Phase 1) :\n"
        + "\n".join(offenders)
        + "\nTODO: si ce sont de faux positifs, affine ORDER_PATTERNS ; "
        "sinon deplace ce code hors de recorder/."
    )


def test_detector_catches_fake_order(tmp_path: Path):
    """Preuve que le detecteur d'ordres fonctionne : un faux appel doit etre signale.

    Cree un dossier temporaire recorder/ contenant le mot place_order
    et verifie que collect_order_offenders le detecte.
    Un detecteur qui ne detecte rien ne doit pas passer.
    """
    # Construction dynamique pour ne pas declencher le detecteur sur ce fichier
    func_name = "place" + "_order"
    fake_recorder = tmp_path / "recorder"
    fake_recorder.mkdir()
    (fake_recorder / "fake_recorder.py").write_text(
        f"def {func_name}(symbol, size):\n    pass\n",
        encoding="utf-8",
    )
    offenders = collect_order_offenders(fake_recorder, tmp_path)
    assert offenders, (
        "Le detecteur d'ordres n'a rien signale alors qu'un fichier temporaire "
        f"contenant {func_name} a ete cree dans recorder/. Le detecteur est casse."
    )
    assert any(func_name in o for o in offenders), (
        f"Le detecteur a signale quelque chose mais pas le motif attendu : {offenders}"
    )
