"""
Garde-fou : echoue si une valeur ressemblant a une cle ou un mot de passe
est trouvee dans les fichiers du depot.

Ignore : .env (fichier reel avec secrets), venv/.venv/env, caches, data/, .git/.
N'analyse que les fichiers texte. Signale les affectations suspectes ou une
variable sensible (API key, password, secret, token) est suivie d'une valeur
reelle entre guillemets.
"""

import re
from pathlib import Path

import pytest

# Valeurs qui ne sont PAS considerees comme secrets (placeholders autorises)
PLACEHOLDER_VALUES = {
    "",
    "demo",
    "false",
    "true",
    "example",
    "changeme",
    "xxx",
    "your_key_here",
    "your_api_key",
    "your_password",
}

# Repertoire racine du depot (parent de tests/)
ROOT = Path(__file__).resolve().parents[1]

# Dossiers a ignorer completement
IGNORED_DIRS = {
    ".git",
    "venv",
    ".venv",
    "env",
    "ENV",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "data",
    ".hg",
}

# Fichiers a ignorer (secrets legitimes non versionnes)
IGNORED_FILES = {
    ".env",
}

# Extensions binaires a ignorer
IGNORED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".parquet",
    ".db",
    ".whl",
}

# Motif : variable sensible suivie de = ou : puis d'une valeur non vide
# (ex : cle API ou mot de passe suivi de = et d'une valeur entre guillemets)
# On exige au moins 8 caracteres pour la valeur pour eviter les faux positifs
SECRET_ASSIGN_RE = re.compile(
    r"""(?i)                    # insensible a la casse
    (api[_-]?key                # api_key, apikey, api-key
    |identifier                 # CAPITAL_IDENTIFIER
    |password
    |passwd
    |secret
    |token)
    \s*[:=]\s*                  # separateur = ou :
    [\"']?                      # guillemet optionnel
    (?P<val>[^\"'\s;]{8,})      # valeur capturee (8+ chars sans espace/guillemet)
    [\"']?
    """,
    re.VERBOSE,
)


def _is_placeholder(val: str) -> bool:
    """Retourne True si la valeur est un placeholder autorise."""
    v = val.strip().strip("\"'").lower()
    if v in PLACEHOLDER_VALUES:
        return True
    # Placeholders avec chevrons du type <valeur> ou <ton_secret>
    if "<" in val or ">" in val:
        return True
    if "valeur" in v:
        return True
    # Valeurs type ${VAR} ou $VAR non resolues
    if v.startswith("${") or v.startswith("$"):
        return True
    # Valeurs tres courtes ou evidentes
    if v in ("", "null", "none"):
        return True
    return False


def _should_skip(path: Path) -> bool:
    """Decide si un fichier doit etre ignore."""
    # Fichier explicitement ignore
    if path.name in IGNORED_FILES:
        return True
    # Dossier ignore
    for part in path.parts:
        if part in IGNORED_DIRS:
            return True
    # Extension binaire
    if path.suffix.lower() in IGNORED_SUFFIXES:
        return True
    return False


def collect_secret_offenders(root: Path = ROOT) -> list[str]:
    """Scanne root et retourne la liste des lignes suspectes.

    Fonction publique et testable : accepte un dossier racine en parametre
    pour pouvoir etre verifiee sur un dossier temporaire.
    """
    offenders: list[str] = []
    root = Path(root)
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if _should_skip(p):
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
        except OSError:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            m = SECRET_ASSIGN_RE.search(line)
            if m:
                val = m.group("val")
                val = val.rstrip(",);")
                if _is_placeholder(val):
                    continue
                if val.startswith("os.") or val.startswith("environ"):
                    continue
                offenders.append(f"{p.relative_to(root)}:{lineno}: {line.strip()}  -> valeur='{val}'")
    return offenders


def test_no_hardcoded_secrets():
    """Parcourt le depot et echoue si une vraie cle est trouvee (hors .env et venv)."""
    offenders = collect_secret_offenders(ROOT)
    assert not offenders, (
        "Valeurs ressemblant a des cles/mots de passe trouvees dans le depot "
        "(hors .env et venv). Deplace-les dans .env (ignore par git) :\n"
        + "\n".join(offenders)
    )


def test_detector_catches_fake_secret(tmp_path: Path):
    """Preuve que le detecteur fonctionne : une fausse cle doit etre signalee.

    Cree un fichier temporaire (hors depot) contenant une fausse cle
    et verifie que collect_secret_offenders la detecte.
    Un detecteur qui ne detecte rien ne doit pas passer.
    """
    key_name = "CAPITAL" + "_API_KEY"
    fake_value = "abcdef" + "1234567890" + "abcdef"
    fake_content = f'{key_name}="{fake_value}"\n'
    (tmp_path / "fake_config.py").write_text(fake_content, encoding="utf-8")

    offenders = collect_secret_offenders(tmp_path)
    assert offenders, (
        "Le detecteur n'a rien signale alors qu'un fichier temporaire "
        f"contenant {key_name} avec une fausse valeur a ete cree. "
        "Le detecteur est casse."
    )
    assert any(fake_value in o for o in offenders), (
        f"Le detecteur a signale quelque chose mais pas la fausse valeur attendue : {offenders}"
    )
