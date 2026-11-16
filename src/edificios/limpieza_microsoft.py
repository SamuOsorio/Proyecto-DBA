"""e06+e07+e08 (Maria Camila): prefiltro, limpieza y Parquet de Microsoft.

Entrada:  los .csv.gz que deja descarga_microsoft.py (GeoJSON, un Feature por
          línea, solo geometría; `confidence` y `height` vienen en -1).
Salida:   config.yaml -> edificios.salida_parquet.microsoft  (contrato en
          src/edificios/comun.py) y data/processed/control_microsoft.csv.

Por cada archivo, en procesos paralelos y sin cargarlo todo en memoria:
  1. Lee las líneas y construye las geometrías con shapely.
  2. Filtra: el centroide debe caer dentro de la unión de los municipios PDET.
  3. Valida, repara (make_valid), calcula área en EPSG:9377 y geom_hash.
  4. Escribe un Parquet parcial.
Al final une las partes con DuckDB y elimina duplicados por geom_hash.

"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import shapely

from src.common.config import ROOT, load_config, mongo_uri
from src.edificios.comun import (ESTADISTICAS, GEO_METADATA, cargar_union_pdet,
                                 escribir_parquet, limpiar_bloque)

_UNION = None


def _iniciar_proceso() -> None:
    global _UNION
    _UNION = cargar_union_pdet()


def _procesar_archivo(args: tuple[str, str]) -> dict:
    ruta, carpeta_partes = args
    ruta = Path(ruta)
    quadkey = ruta.name.removeprefix("quadkey_").removesuffix(".csv.gz")
    t0 = time.perf_counter()
    with gzip.open(ruta, "rt", encoding="utf-8") as f:
        lineas = [linea for linea in f if linea.strip()]
    geoms = shapely.from_geojson(lineas, on_invalid="ignore")
    df, st = limpiar_bloque(geoms, _UNION, "microsoft")
    st["geometrias_ilegibles"] = int(shapely.is_missing(geoms).sum())
    if len(df):
        escribir_parquet(df, Path(carpeta_partes) / f"{quadkey}.parquet")
    st.update(quadkey=quadkey, segundos=round(time.perf_counter() - t0, 2))
    return st


def _unir_partes(carpeta_partes: Path, salida: Path) -> int:
    """Une los Parquet parciales y deja un solo registro por geom_hash."""
    salida.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    patron = str(carpeta_partes / "*.parquet")
    # KV_METADATA con "geo": deja el Parquet como GeoParquet (igual que el de Google)
    geo = json.dumps(GEO_METADATA).replace("'", "''")
    con.execute(f"""
        COPY (SELECT DISTINCT ON (geom_hash) * FROM read_parquet('{patron}'))
        TO '{salida}' (FORMAT parquet, COMPRESSION zstd, KV_METADATA {{geo: '{geo}'}})""")
    return con.execute(f"SELECT count(*) FROM read_parquet('{salida}')").fetchone()[0]


def _registrar_bitacora(cfg: dict, doc: dict, n_registros: int) -> None:
    try:
        from pymongo import MongoClient
        db = MongoClient(mongo_uri(cfg), serverSelectionTimeoutMS=5000)[cfg["database"]["name"]]
        db[cfg["database"]["collections"]["bitacora_cargas"]].insert_one(doc)
        db[cfg["database"]["collections"]["fuentes"]].update_one(
            {"_id": "microsoft"}, {"$set": {"n_registros": n_registros}})
        print("Etapa registrada en `bitacora_cargas`.")
    except Exception as e:
        print(f"AVISO: no se pudo registrar en MongoDB ({e}).")


def limpiar_microsoft(limite: int | None = None) -> Path:
    cfg = load_config()
    entrada = ROOT / cfg["fuentes"]["microsoft_building_footprints"]["destino_local"]
    salida = ROOT / cfg["edificios"]["salida_parquet"]["microsoft"]
    partes = ROOT / "data/processed/microsoft_partes"
    shutil.rmtree(partes, ignore_errors=True)
    partes.mkdir(parents=True)

    archivos = sorted(entrada.glob("quadkey_*.csv.gz"))
    if limite:
        archivos = archivos[:limite]
    if not archivos:
        raise FileNotFoundError(f"No hay quadkey_*.csv.gz en {entrada}; corre descarga_microsoft.py")
    print(f"[limpieza] {len(archivos)} archivos, {cfg['edificios']['procesos']} procesos.")

    inicio = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=cfg["edificios"]["procesos"],
                             initializer=_iniciar_proceso) as pool:
        filas = list(pool.map(_procesar_archivo, [(str(a), str(partes)) for a in archivos]))
    t_limpieza = time.perf_counter() - t0

    t1 = time.perf_counter()
    unicos = _unir_partes(partes, salida)
    t_union = time.perf_counter() - t1
    shutil.rmtree(partes, ignore_errors=True)

    # Tabla de control por archivo y total (va al informe)
    control = pd.DataFrame(filas).sort_values("quadkey")
    columnas = ["quadkey", *ESTADISTICAS, "geometrias_ilegibles", "segundos"]
    control = control[columnas]
    total = control.drop(columns="quadkey").sum()
    fila_total = pd.DataFrame([{"quadkey": "TOTAL", **total.to_dict()}])
    control = pd.concat([control, fila_total], ignore_index=True)
    control.to_csv(ROOT / "data/processed/control_microsoft.csv", index=False)

    t = total
    duplicados = int(t["conservados"]) - unicos
    print("\n=== CONTROL MICROSOFT ===")
    print(f"Registros leídos            : {int(t['leidos']):>10,}")
    print(f"Geometrías ilegibles        : {int(t['geometrias_ilegibles']):>10,}")
    print(f"Fuera de los municipios PDET: {int(t['fuera_pdet']):>10,}")
    print(f"Dentro de PDET              : {int(t['dentro_pdet']):>10,}")
    print(f"  inválidos (reparados)     : {int(t['invalidos']):>10,}")
    print(f"  descartados               : {int(t['descartados']):>10,}")
    print(f"Duplicados por geom_hash    : {duplicados:>10,}")
    print(f"Edificios en el Parquet     : {unicos:>10,}")
    print(f"Tiempo: limpieza {t_limpieza:.1f} s, unión {t_union:.1f} s; "
          f"{salida.stat().st_size / 1e6:.1f} MB en {salida.relative_to(ROOT)}")

    _registrar_bitacora(cfg, {
        "fuente_id": "microsoft", "etapa": "limpieza",
        "inicio": inicio, "fin": datetime.now(timezone.utc),
        "registros_ok": int(unicos),
        "registros_error": int(t["sin_geometria"] + t["geometrias_ilegibles"] + t["descartados"]),
        "parametros": {"archivos": len(archivos), "leidos": int(t["leidos"]),
                       "fuera_pdet": int(t["fuera_pdet"]), "duplicados": duplicados,
                       "segundos_limpieza": round(t_limpieza, 1),
                       "segundos_union": round(t_union, 1)},
    }, int(unicos))
    return salida


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, help="procesar solo los N primeros archivos (pruebas)")
    limpiar_microsoft(ap.parse_args().limite)
