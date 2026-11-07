"""Carga config.yaml y las variables de entorno compartidas por todos los scripts de src/."""
from pathlib import Path
import os
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

load_dotenv(ROOT / ".env")


def load_config(path: Path | str = ROOT / "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def mongo_uri(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    env_var = cfg["database"]["uri_env_var"]
    uri = os.environ.get(env_var)
    if not uri:
        raise RuntimeError(f"Falta {env_var} en el entorno (ver .env.example)")
    return uri
