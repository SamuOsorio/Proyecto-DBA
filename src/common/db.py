"""Conexión compartida a MongoDB para todos los scripts de src/."""
from pymongo import MongoClient
from pymongo.database import Database

from src.common.config import load_config, mongo_uri

_client: MongoClient | None = None


def get_database() -> Database:
    global _client
    cfg = load_config()
    if _client is None:
        _client = MongoClient(mongo_uri(cfg))
    return _client[cfg["database"]["name"]]
