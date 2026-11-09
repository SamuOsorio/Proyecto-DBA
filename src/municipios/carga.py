"""t10 (Samuel): carga municipios_pdet.geojson en MongoDB con PyMongo.

Debe:
  - Leer config.yaml -> municipios.salida_geojson (lo produce exportar.py).
  - Carga idempotente: upsert por `_id` (código DANE), no insert_many ciego.
  - Registrar la ejecución en `bitacora_cargas` (etapa="carga").
"""
import json
from datetime import datetime, timezone

from pymongo import UpdateOne

from src.common.db import get_database
from src.municipios.geometria import cargar_config, ruta


def _leer_features(cfg: dict) -> list[dict]:
    with open(ruta(cfg, "salida_geojson"), encoding="utf-8") as f:
        coleccion = json.load(f)
    return coleccion["features"]


def cargar_municipios():
    cfg = cargar_config()
    db = get_database()
    coleccion = db[cfg["database"]["collections"]["municipios"]]

    features = _leer_features(cfg)
    inicio = datetime.now(timezone.utc)

    operaciones = []
    for feature in features:
        doc = dict(feature["properties"])
        doc["geometry"] = feature["geometry"]
        operaciones.append(UpdateOne({"_id": doc["_id"]}, {"$set": doc}, upsert=True))

    registros_ok, registros_error = 0, 0
    if operaciones:
        resultado = coleccion.bulk_write(operaciones, ordered=False)
        registros_ok = resultado.upserted_count + resultado.modified_count + resultado.matched_count
        registros_error = len(operaciones) - registros_ok

    fin = datetime.now(timezone.utc)
    total = coleccion.count_documents({})
    print(f"[carga] {len(operaciones)} municipios procesados; {total} en la colección.")

    db[cfg["database"]["collections"]["fuentes"]].update_one(
        {"_id": "mgn"}, {"$set": {"n_registros": total}}
    )

    db[cfg["database"]["collections"]["bitacora_cargas"]].insert_one({
        "fuente_id": "mgn",
        "etapa": "carga",
        "inicio": inicio,
        "fin": fin,
        "registros_ok": registros_ok,
        "registros_error": registros_error,
        "parametros": {"archivo": str(ruta(cfg, "salida_geojson"))},
    })

    return {"registros_ok": registros_ok, "registros_error": registros_error, "total": total}


if __name__ == "__main__":
    cargar_municipios()
