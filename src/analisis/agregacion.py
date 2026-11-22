"""Agregación por municipio en `resultados` (semana 4, Samuel).

Para cada fuente (y, en Google, cada umbral de confianza de config.yaml) corre
una sola pipeline en MongoDB:

    $match (cod_mpio asignado; confianza >= umbral en Google)
      -> $group por cod_mpio (conteo, suma y media de area_m2)
      -> $lookup a municipios (área del municipio)
      -> $project (densidad y % de techos, llave {cod_mpio, fuente_id, umbral})
      -> $merge a resultados

Después completa con ceros los municipios sin edificios, para que siempre haya
170 documentos por fuente y umbral. Antes de escribir borra los documentos de
esa fuente y umbral, así correrlo dos veces deja exactamente lo mismo.

Cambio respecto al diccionario de la Entrega 1: el `_id` pasa de
{cod_mpio, fuente_id} a {cod_mpio, fuente_id, umbral} para guardar la
sensibilidad en la misma colección. Microsoft lleva umbral null.

Uso:
  python -m src.analisis.agregacion            # todas las fuentes y umbrales
  python -m src.analisis.agregacion google     # solo una fuente
"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone

from pymongo.errors import CollectionInvalid

from src.common.config import ROOT, load_config
from src.common.db import get_database

FUENTES = ("google", "microsoft")

VALIDATOR_RESULTADOS = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "_id", "n_edificios", "area_total_m2", "area_media_m2",
            "densidad_km2", "pct_techos", "parametros", "fecha_calculo",
        ],
        "properties": {
            "_id": {
                "bsonType": "object",
                "required": ["cod_mpio", "fuente_id", "umbral"],
                "additionalProperties": False,
                "properties": {
                    "cod_mpio": {"bsonType": "string", "pattern": "^[0-9]{5}$"},
                    "fuente_id": {"enum": ["google", "microsoft"]},
                    "umbral": {"bsonType": ["double", "null"], "minimum": 0, "maximum": 1},
                },
            },
            "n_edificios": {"bsonType": ["int", "long"], "minimum": 0},
            "area_total_m2": {"bsonType": "double", "minimum": 0},
            # null cuando el municipio no tiene edificios (no hay media)
            "area_media_m2": {"bsonType": ["double", "null"], "minimum": 0},
            "densidad_km2": {"bsonType": "double", "minimum": 0},
            "pct_techos": {"bsonType": "double", "minimum": 0, "maximum": 100},
            "parametros": {
                "bsonType": "object",
                "required": ["umbral", "regla_asignacion", "crs_area", "version_codigo"],
            },
            "fecha_calculo": {"bsonType": "date"},
        },
    }
}


# ------------------------------------------------------------------ esquema
def crear_coleccion_resultados(db, nombre: str) -> None:
    """Crea `resultados` con $jsonSchema; si ya existe, le pone el validador actual."""
    try:
        db.create_collection(nombre, validator=VALIDATOR_RESULTADOS, validationLevel="strict")
        print(f"[agregacion] Colección `{nombre}` creada con validación $jsonSchema.")
    except CollectionInvalid:
        db.command("collMod", nombre, validator=VALIDATOR_RESULTADOS, validationLevel="strict")
        print(f"[agregacion] Colección `{nombre}` ya existía; validador actualizado (collMod).")


# --------------------------------------------------------------- utilidades
def version_codigo() -> str:
    """Commit actual del repositorio (con '+cambios' si hay archivos sin commitear)."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        sucio = subprocess.run(["git", "status", "--porcelain", "--", "src", "config.yaml"],
                               cwd=ROOT, capture_output=True, text=True).stdout.strip()
        return sha + ("+cambios" if sucio else "")
    except (OSError, subprocess.CalledProcessError):
        return "desconocida"


def umbrales_de(fuente: str, cfg: dict) -> list[float | None]:
    if fuente == "google":
        return [float(u) for u in cfg["analisis"]["umbrales_google"]]
    return [None]  # Microsoft no trae confianza


def filtro_edificios(umbral: float | None) -> dict:
    """Mismo filtro para la pipeline y para la verificación."""
    filtro: dict = {"cod_mpio": {"$ne": None}}
    if umbral is not None:
        filtro["confianza"] = {"$gte": umbral}
    return filtro


def parametros(fuente: str, umbral: float | None, cfg: dict, version: str) -> dict:
    return {
        "umbral": umbral,
        "regla_asignacion": cfg["analisis"]["regla_asignacion"],
        "crs_area": cfg["crs"]["calculo_areas"],
        "coleccion_origen": cfg["database"]["collections"][f"edificios_{fuente}"],
        "version_codigo": version,
    }


# ---------------------------------------------------------------- pipelines
def pipeline_agregacion(fuente: str, umbral: float | None, cfg: dict, params: dict) -> list[dict]:
    col = cfg["database"]["collections"]
    return [
        {"$match": filtro_edificios(umbral)},
        {"$group": {
            "_id": "$cod_mpio",
            "n": {"$sum": 1},
            "area": {"$sum": "$area_m2"},
            "media": {"$avg": "$area_m2"},
        }},
        {"$lookup": {"from": col["municipios"], "localField": "_id",
                     "foreignField": "_id", "as": "m"}},
        {"$unwind": "$m"},
        {"$project": {
            "_id": {"cod_mpio": "$_id", "fuente_id": {"$literal": fuente},
                    "umbral": {"$literal": umbral}},
            "n_edificios": "$n",
            "area_total_m2": "$area",
            "area_media_m2": "$media",
            "densidad_km2": {"$divide": ["$n", "$m.area_km2"]},
            # área de techos / área del municipio (km² -> m²), en %
            "pct_techos": {"$multiply": [100, {"$divide": [
                "$area", {"$multiply": ["$m.area_km2", 1e6]}]}]},
            "parametros": {"$literal": params},
            "fecha_calculo": "$$NOW",
        }},
        {"$merge": {"into": col["resultados"], "on": "_id",
                    "whenMatched": "replace", "whenNotMatched": "insert"}},
    ]


def pipeline_ceros(fuente: str, umbral: float | None, cfg: dict, params: dict) -> list[dict]:
    """Un documento en cero por municipio que la agregación no produjo."""
    return [
        {"$project": {
            "_id": {"cod_mpio": "$_id", "fuente_id": {"$literal": fuente},
                    "umbral": {"$literal": umbral}},
            "n_edificios": {"$literal": 0},
            "area_total_m2": {"$literal": 0.0},
            "area_media_m2": {"$literal": None},
            "densidad_km2": {"$literal": 0.0},
            "pct_techos": {"$literal": 0.0},
            "parametros": {"$literal": params},
            "fecha_calculo": "$$NOW",
        }},
        {"$merge": {"into": cfg["database"]["collections"]["resultados"], "on": "_id",
                    "whenMatched": "keepExisting", "whenNotMatched": "insert"}},
    ]


# ---------------------------------------------------------------- ejecución
def agregar(fuente: str, umbral: float | None, cfg: dict | None = None,
            version: str | None = None) -> dict:
    cfg = cfg or load_config()
    db = get_database()
    col = cfg["database"]["collections"]
    resultados = db[col["resultados"]]
    params = parametros(fuente, umbral, cfg, version or version_codigo())
    clave = {"_id.fuente_id": fuente, "_id.umbral": umbral}

    t0 = time.perf_counter()
    borrados = resultados.delete_many(clave).deleted_count
    db[col[f"edificios_{fuente}"]].aggregate(
        pipeline_agregacion(fuente, umbral, cfg, params), allowDiskUse=True)
    con_datos = resultados.count_documents(clave)
    db[col["municipios"]].aggregate(pipeline_ceros(fuente, umbral, cfg, params))
    total = resultados.count_documents(clave)
    seg = time.perf_counter() - t0

    etiqueta = f"{fuente}" + (f" umbral {umbral:.2f}" if umbral is not None else "")
    print(f"[agregacion] {etiqueta}: {con_datos} municipios con edificios, "
          f"{total - con_datos} en cero, {total} documentos ({seg:.1f} s; "
          f"{borrados} documentos anteriores reemplazados).")
    return {"fuente": fuente, "umbral": umbral, "documentos": total,
            "con_edificios": con_datos, "en_cero": total - con_datos,
            "segundos": round(seg, 2)}


def verificar(fuente: str, umbral: float | None, cfg: dict | None = None) -> dict:
    """170 documentos y suma de n_edificios = edificios asignados que pasan el filtro."""
    cfg = cfg or load_config()
    db = get_database()
    col = cfg["database"]["collections"]
    n_mpios = db[col["municipios"]].count_documents({})
    clave = {"_id.fuente_id": fuente, "_id.umbral": umbral}
    docs = db[col["resultados"]].count_documents(clave)
    suma = next(db[col["resultados"]].aggregate([
        {"$match": clave}, {"$group": {"_id": None, "n": {"$sum": "$n_edificios"}}}]),
        {"n": 0})["n"]
    esperado = db[col[f"edificios_{fuente}"]].count_documents(filtro_edificios(umbral))
    sin_mpio = db[col[f"edificios_{fuente}"]].count_documents({"cod_mpio": None})
    ok = docs == n_mpios and suma == esperado
    r = {"fuente": fuente, "umbral": umbral, "documentos": docs, "municipios": n_mpios,
         "suma_n_edificios": suma, "edificios_esperados": esperado,
         "sin_municipio": sin_mpio, "ok": ok}
    estado = "OK" if ok else "FALLA"
    print(f"[verificacion] {fuente} {umbral}: {docs}/{n_mpios} documentos, "
          f"suma {suma:,} vs. {esperado:,} esperados ({sin_mpio} sin municipio) -> {estado}")
    return r


def agregar_todo(fuentes=FUENTES) -> list[dict]:
    cfg = load_config()
    db = get_database()
    col = cfg["database"]["collections"]
    base = float(cfg["edificios"]["umbral_confianza_google_default"])
    if float(cfg["analisis"]["umbrales_google"][0]) != base:
        raise ValueError("analisis.umbrales_google[0] debe ser el umbral base "
                         f"({base}) de edificios.umbral_confianza_google_default")

    for fuente in fuentes:
        if db[col[f"edificios_{fuente}"]].count_documents({"cod_mpio": {"$ne": None}}, limit=1) == 0:
            raise RuntimeError(f"`edificios_{fuente}` no tiene cod_mpio asignado. "
                               "Corre antes `python -m src.analisis.asignacion`.")

    crear_coleccion_resultados(db, col["resultados"])
    version = version_codigo()
    salida = []
    for fuente in fuentes:
        inicio = datetime.now(timezone.utc)
        corridas = [agregar(fuente, u, cfg, version) for u in umbrales_de(fuente, cfg)]
        checks = [verificar(fuente, u, cfg) for u in umbrales_de(fuente, cfg)]
        db[col["bitacora_cargas"]].insert_one({
            "fuente_id": fuente, "etapa": "analisis",
            "inicio": inicio, "fin": datetime.now(timezone.utc),
            "registros_ok": sum(c["documentos"] for c in corridas),
            "registros_error": sum(not c["ok"] for c in checks),
            "parametros": {"paso": "agregacion", "version_codigo": version,
                           "umbrales": umbrales_de(fuente, cfg),
                           "corridas": corridas, "verificacion": checks},
        })
        for c, v in zip(corridas, checks):
            salida.append({**c, **{k: v[k] for k in ("suma_n_edificios", "edificios_esperados",
                                                      "sin_municipio", "ok")}})

    fallas = [s for s in salida if not s["ok"]]
    if fallas:
        raise RuntimeError(f"La verificación de resultados falló en: {fallas}")
    print(f"[agregacion] {len(salida)} combinaciones fuente/umbral escritas y verificadas "
          "(registrado en bitacora_cargas).")
    return salida


if __name__ == "__main__":
    pedidas = sys.argv[1:] or list(FUENTES)
    malas = [f for f in pedidas if f not in FUENTES]
    if malas:
        sys.exit(f"fuente desconocida: {malas}; usa {list(FUENTES)}")
    agregar_todo(tuple(pedidas))
