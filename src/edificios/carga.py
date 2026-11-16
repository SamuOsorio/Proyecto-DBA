"""e10 (Samuel): carga un Parquet de edificios en MongoDB por lotes.

Uso: python -m src.edificios.carga microsoft   (o google)

Decisiones:
  - Lee el Parquet por lotes con pyarrow (nunca entero en memoria).
  - `insert_many(ordered=False)` de 5000 documentos (config:
    edificios.tamano_lote_insercion): un documento malo no frena el lote.
  - Los índices (salvo `_id`) se borran antes. El 2dsphere de `geometry` se
    crea ANTES de cargar a propósito: MongoDB valida cada polígono con
    geometría esférica (S2) y rechaza algunos que GEOS da por válidos (aristas
    casi tocándose, ~2 por millón). Con el índice activo el rechazo es por
    documento; se reparan con set_precision(1e-6) (~11 cm) y se reintentan.
    Los demás índices se crean después (indices.py).
  - Idempotente: borra los documentos previos de la misma fuente antes de cargar.
  - Cada carga es un `lote_id` (ObjectId) que también es el `_id` de su fila
    en `bitacora_cargas`.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone

import pyarrow.parquet as pq
import shapely
from bson import ObjectId
from pymongo.errors import BulkWriteError

from src.common.config import ROOT, load_config
from src.common.db import get_database

COLUMNAS = ["fuente_id", "geometry", "centroide_lon", "centroide_lat",
            "area_m2", "area_m2_fuente", "confianza", "geom_hash"]


def _documentos(lote: dict, lote_id: ObjectId) -> list[dict]:
    """Convierte un lote columnar de Arrow en documentos del esquema de Mongo."""
    geoms = shapely.from_wkb(lote["geometry"])
    docs = []
    for i, geom in enumerate(geoms):
        docs.append({
            "fuente_id": lote["fuente_id"][i],
            "geometry": shapely.geometry.mapping(geom),
            "centroide": {"type": "Point",
                          "coordinates": [lote["centroide_lon"][i], lote["centroide_lat"][i]]},
            "area_m2": lote["area_m2"][i],
            "area_m2_fuente": lote["area_m2_fuente"][i],
            "confianza": lote["confianza"][i],
            "cod_mpio": None,
            "geom_hash": lote["geom_hash"][i],
            "lote_id": lote_id,
        })
    return docs


def _reparar_s2(doc: dict) -> dict | None:
    """Reintento para un polígono que S2 rechazó: redondeo a ~11 cm; si no, casco convexo."""
    geom = shapely.geometry.shape(doc["geometry"])
    for arreglo in (lambda g: shapely.set_precision(g, 1e-6), shapely.convex_hull):
        g = arreglo(geom)
        if g.geom_type == "MultiPolygon":
            g = max(g.geoms, key=lambda p: p.area)
        if g.geom_type == "Polygon" and not g.is_empty:
            nuevo = {k: v for k, v in doc.items() if k != "_id"}
            nuevo["geometry"] = shapely.geometry.mapping(g)
            return nuevo
    return None


def cargar(fuente: str) -> dict:
    cfg = load_config()
    db = get_database()
    coleccion = db[cfg["database"]["collections"][f"edificios_{fuente}"]]
    ruta = ROOT / cfg["edificios"]["salida_parquet"][fuente]
    tamano = cfg["edificios"]["tamano_lote_insercion"]
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta}; corre antes la limpieza de {fuente}.")

    lote_id = ObjectId()
    inicio = datetime.now(timezone.utc)

    # Idempotencia + velocidad: sin índices (salvo _id) y sin datos previos.
    coleccion.drop_indexes()
    borrados = coleccion.delete_many({"fuente_id": fuente}).deleted_count
    if borrados:
        print(f"[carga] {borrados:,} documentos previos de `{fuente}` borrados.")

    coleccion.create_index([("geometry", "2dsphere")], name="geometry_2dsphere")

    archivo = pq.ParquetFile(ruta)
    total = archivo.metadata.num_rows
    ok = errores = reparados = 0
    t0 = time.perf_counter()

    for batch in archivo.iter_batches(batch_size=tamano, columns=COLUMNAS):
        docs = _documentos(batch.to_pydict(), lote_id)
        try:
            coleccion.insert_many(docs, ordered=False)
            ok += len(docs)
        except BulkWriteError as e:
            rechazados = [docs[w["index"]] for w in e.details["writeErrors"]]
            ok += len(docs) - len(rechazados)
            for doc in rechazados:
                nuevo = _reparar_s2(doc)
                try:
                    if nuevo is None:
                        raise ValueError("sin reparación posible")
                    coleccion.insert_one(nuevo)
                    ok += 1
                    reparados += 1
                except Exception:
                    errores += 1
                    print(f"[carga] descartado geom_hash={doc['geom_hash']}")
        if (ok + errores) % (tamano * 40) == 0:
            print(f"[carga] {ok + errores:,}/{total:,}", flush=True)

    segundos = time.perf_counter() - t0
    fin = datetime.now(timezone.utc)
    en_coleccion = coleccion.count_documents({"fuente_id": fuente})
    velocidad = ok / segundos if segundos else 0
    print(f"[carga] {fuente}: {ok:,} insertados, {errores:,} rechazados, "
          f"{reparados} reparados para S2, "
          f"{en_coleccion:,} en la colección, {segundos:.1f} s ({velocidad:,.0f} docs/s).")

    db[cfg["database"]["collections"]["fuentes"]].update_one(
        {"_id": fuente}, {"$set": {"n_registros": en_coleccion}})
    db[cfg["database"]["collections"]["bitacora_cargas"]].insert_one({
        "_id": lote_id,
        "fuente_id": fuente,
        "etapa": "carga",
        "inicio": inicio,
        "fin": fin,
        "registros_ok": ok,
        "registros_error": errores,
        "parametros": {"reparados_s2": reparados, "archivo": str(ruta.relative_to(ROOT)), "tamano_lote": tamano,
                       "segundos": round(segundos, 2), "docs_por_segundo": round(velocidad)},
    })
    return {"fuente": fuente, "ok": ok, "errores": errores, "reparados_s2": reparados, "segundos": segundos,
            "docs_por_segundo": velocidad, "lote_id": lote_id}


if __name__ == "__main__":
    fuentes = sys.argv[1:] or ["google", "microsoft"]
    for f in fuentes:
        cargar(f)
