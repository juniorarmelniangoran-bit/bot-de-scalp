# recorder/config.py -- Configuration TOML pour les enregistreurs (sans reseau, sans secret)
# Toute la config vient du fichier TOML + variables d'environnement ; cles API depuis env uniquement.
# Portable Windows/Linux : aucun chemin absolu Windows en dur, tout via pathlib.Path.

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# tomllib est dans la bibliotheque standard depuis Python 3.11
try:
    import tomllib  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

# Defaut portable : ~/bot-data (surchargeable par BOT_DATA_DIR / CAPITAL_DATA_DIR)
# Exemple si BOT_DATA_DIR est defini : BOT_DATA_DIR/databento/mbo (portable, via pathlib.Path)
DEFAULT_OUT_DIR = Path.home() / "bot-data"


@dataclass(frozen=True)
class RecorderConfig:
    dataset: str = "GLBX.MDP3"
    schema: str = "mbo"
    stype_in: str = "continuous"
    symbols: str = "6E.v.0"
    out_dir: Path = Path.home() / "bot-data" / "databento" / "mbo"
    rollover_check_hour_utc: str = "10:00"
    min_free_bytes: int = 1_000_000_000  # 1 Go
    snapshot: bool = True


@dataclass(frozen=True)
class CapitalConfig:
    epic: str = "EURUSD"
    # Base URL demo par defaut (doc https://open-api.capital.com/ : demo-api-capital.backend-capital.com)
    # Flux prix = WebSocket wss://api-streaming-capital.backend-capital.com/connect (doc citee, ping /10 min, max 40 epics)
    base_url: str = "https://demo-api-capital.backend-capital.com"
    poll_ms: int = 1000  # secours REST ponctuel ; flux principal = WebSocket (bid/bidQty/ofr/ofrQty/timestamp)
    out_dir: Path = Path.home() / "bot-data" / "capital"
    min_free_bytes: int = 1_000_000_000
    session_refresh_s: int = 540  # 9 min < 10 min (session active 10 min, doc open-api.capital.com)
    rate_limit_per_second: int = 10
    ws_enabled: bool = True  # flux prix = WebSocket ; REST = session/ping/markets
    ws_url: str = "wss://api-streaming-capital.backend-capital.com/connect"
    ws_max_epics: int = 40
    ws_ping_interval_s: int = 300  # 5 min < 10 min (doc: ping au moins /10 min ; 5 min = marge)


def _resolve_out_dir(env_name: str, subpath: str, toml_value: str | None) -> Path:
    # 1) variable d'environnement prime (portable)
    env_val = os.environ.get(env_name)
    # Pour databento on garde BOT_DATA_DIR ; pour capital on accepte CAPITAL_DATA_DIR sinon BOT_DATA_DIR/capital
    if env_val:
        return Path(env_val) / subpath
    if env_name == "CAPITAL_DATA_DIR" and os.environ.get("BOT_DATA_DIR"):
        # fallback : BOT_DATA_DIR/capital si CAPITAL_DATA_DIR non defini
        return Path(os.environ["BOT_DATA_DIR"]) / "capital"
    if toml_value:
        # expanduser pour ~/bot-data
        return Path(str(toml_value)).expanduser()
    return Path.home() / "bot-data" / subpath


def load_config(toml_path: str | os.PathLike[str]) -> RecorderConfig:
    """Charge la config Databento depuis un fichier TOML.

    Cles attendues dans [recorder] : dataset, schema, stype_in, symbols,
    out_dir, rollover_check_hour_utc, min_free_bytes, snapshot.
    Variables d'environnement :
      - BOT_DATA_DIR : surcharge out_dir (hors dossier synchro cloud, portable)
      - DATABENTO_API_KEY : jamais lue ici, juste rappelee pour doc.
    """
    p = Path(toml_path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"fichier de config introuvable : {p}")
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    rec = data.get("recorder", data)

    out_dir_raw = rec.get("out_dir")
    env_out = os.environ.get("BOT_DATA_DIR")
    if env_out:
        out_dir = Path(env_out) / "databento" / "mbo"
    elif out_dir_raw:
        out_dir = Path(str(out_dir_raw)).expanduser()
    else:
        out_dir = Path.home() / "bot-data" / "databento" / "mbo"

    return RecorderConfig(
        dataset=str(rec.get("dataset", "GLBX.MDP3")),
        schema=str(rec.get("schema", "mbo")),
        stype_in=str(rec.get("stype_in", "continuous")),
        symbols=str(rec.get("symbols", "6E.v.0")),
        out_dir=out_dir,
        rollover_check_hour_utc=str(rec.get("rollover_check_hour_utc", "10:00")),
        min_free_bytes=int(rec.get("min_free_bytes", 1_000_000_000)),
        snapshot=bool(rec.get("snapshot", True)),
    )


def load_capital_config(toml_path: str | os.PathLike[str]) -> CapitalConfig:
    """Charge la config Capital.com demo depuis TOML.

    Section [capital] : epic, base_url, poll_ms, out_dir, min_free_bytes,
    session_refresh_s, rate_limit_per_second, ws_enabled, ws_url, ws_max_epics, ws_ping_interval_s.
    Env : CAPITAL_DATA_DIR (prime), sinon BOT_DATA_DIR/capital, sinon ~/bot-data/capital.
    Cles API : CAPITAL_API_KEY / CAPITAL_IDENTIFIER / CAPITAL_PASSWORD depuis env uniquement
    via BOT_ENV_FILE (fichier hors projet, ex ~/secrets/bot.env).
    """
    p = Path(toml_path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"fichier de config introuvable : {p}")
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    cap = data.get("capital", {})

    out_dir_raw = cap.get("out_dir")
    # CAPITAL_DATA_DIR prime, sinon BOT_DATA_DIR/capital, sinon toml/~/bot-data/capital
    if os.environ.get("CAPITAL_DATA_DIR"):
        out_dir = Path(os.environ["CAPITAL_DATA_DIR"])
    elif os.environ.get("BOT_DATA_DIR"):
        out_dir = Path(os.environ["BOT_DATA_DIR"]) / "capital"
    elif out_dir_raw:
        out_dir = Path(str(out_dir_raw)).expanduser()
    else:
        out_dir = Path.home() / "bot-data" / "capital"

    return CapitalConfig(
        epic=str(cap.get("epic", "EURUSD")),
        base_url=str(cap.get("base_url", "https://demo-api-capital.backend-capital.com")),
        poll_ms=int(cap.get("poll_ms", 1000)),
        out_dir=out_dir,
        min_free_bytes=int(cap.get("min_free_bytes", 1_000_000_000)),
        session_refresh_s=int(cap.get("session_refresh_s", 540)),
        rate_limit_per_second=int(cap.get("rate_limit_per_second", 10)),
        ws_enabled=bool(cap.get("ws_enabled", True)),
        ws_url=str(cap.get("ws_url", "wss://api-streaming-capital.backend-capital.com/connect")),
        ws_max_epics=int(cap.get("ws_max_epics", 40)),
        ws_ping_interval_s=int(cap.get("ws_ping_interval_s", 300)),
    )


def load_bot_env_file() -> Path | None:
    """Charge le fichier d'env pointe par BOT_ENV_FILE (hors projet) via python-dotenv.

    Retourne le chemin charge ou None si non defini.
    Leve RuntimeError si le fichier est a l'interieur du projet (dossier synchro cloud).
    Ne log jamais les valeurs.
    """
    env_file = os.environ.get("BOT_ENV_FILE")
    if not env_file:
        return None
    p = Path(env_file).expanduser().resolve()
    project_root = Path(__file__).resolve().parents[1]
    try:
        p.relative_to(project_root.resolve())
        raise RuntimeError(
            f"BOT_ENV_FILE doit pointer hors du projet : {p} ; projet={project_root} ; "
            "deplace vers ex ~/secrets/bot.env (hors projet, via BOT_DATA_DIR)"
        )
    except ValueError:
        pass
    if not p.exists():
        raise FileNotFoundError(f"BOT_ENV_FILE introuvable : {p}")
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=p, override=False)
    except Exception:
        pass
    return p


def get_capital_credentials() -> tuple[str | None, str | None, str | None]:
    """Retourne (api_key, identifier, password) depuis l'env (apres load_bot_env_file)."""
    try:
        load_bot_env_file()
    except Exception:
        raise
    return (
        os.environ.get("CAPITAL_API_KEY"),
        os.environ.get("CAPITAL_IDENTIFIER"),
        os.environ.get("CAPITAL_PASSWORD"),
    )

