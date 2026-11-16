"""e11 (Samuel): crea los índices de `edificios_*` DESPUÉS de cargar.

  - 2dsphere sobre `centroide`  -> $geoWithin de la asignación (semana 4)
  - 2dsphere sobre `geometry`   -> $geoIntersects para edificios en los límites
  - `cod_mpio`                  -> agregación por municipio
  - `geom_hash` único           -> sin duplicados entre particiones

Mide el tiempo de cada uno (para el informe).
"""
from __future__ import annotations

import sys
import time

from src.common.config import load_config
from src.common.db import get_database

INDICES = [
    ("centroide_2dsphere", [("centroide", "2dsphere")], {}),
    ("geometry_2dsphere", [("geometry", "2dsphere")], {}),
    ("cod_mpio_1", [("cod_mpio", 1)], {}),
    ("geom_hash_unico", [("geom_hash", 1)], {"unique": True}),
]


def crear_indices(fuente: str) -> list[dict]:
    cfg = load_config()
    coleccion = get_database()[cfg["database"]["collections"][f"edificios_{fuente}"]]
    existentes = {i["name"] for i in coleccion.list_indexes()}
    tiempos = []
    for nombre, claves, opciones in INDICES:
        if nombre in existentes:
            print(f"[indices] {fuente}: {nombre} ya existe.")
            continue
        t0 = time.perf_counter()
        coleccion.create_index(claves, name=nombre, **opciones)
        s = time.perf_counter() - t0
        tiempos.append({"indice": nombre, "segundos": round(s, 1)})
        print(f"[indices] {fuente}: {nombre} creado en {s:.1f} s")
    return tiempos


if __name__ == "__main__":
    for f in (sys.argv[1:] or ["google", "microsoft"]):
        crear_indices(f)
