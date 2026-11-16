"""e12 (Samuel): evidencia de que los índices de `edificios_*` se usan.

Para cada fuente cargada:
  - explain de $geoWithin sobre `centroide` (la consulta de la semana 4):
    debe usar IXSCAN; se contrasta con hint({$natural:1}) = COLLSCAN.
  - explain de $geoIntersects sobre `geometry`.
  - tamaño de colección e índices (collStats).
Guarda la tabla en data/processed/evidencia_edificios.csv para el informe.
"""
from __future__ import annotations

import csv
import sys
import time

import geopandas as gpd

from src.common.config import ROOT, load_config
from src.common.db import get_database


def _etapas(plan: dict) -> list[str]:
    nombres = [plan["stage"]]
    for h in [plan.get("inputStage"), *(plan.get("inputStages") or [])]:
        if isinstance(h, dict):
            nombres.extend(_etapas(h))
    return nombres


def _municipio_prueba(cfg: dict):
    """Un municipio PDET del geojson: su polígono es la ventana de la consulta."""
    gdf = gpd.read_file(ROOT / cfg["municipios"]["salida_geojson"])
    fila = gdf[gdf["_id"] == "19137"]  # Caldono
    fila = fila.iloc[0] if len(fila) else gdf.iloc[0]
    return fila["_id"], fila["nombre"], fila.geometry.__geo_interface__


def _medir(coleccion, filtro, hint=None):
    cur = coleccion.find(filtro, {"_id": 1})
    if hint:
        cur = cur.hint(hint)
    plan = cur.explain()
    etapas = _etapas(plan["queryPlanner"]["winningPlan"])
    t0 = time.perf_counter()
    n = coleccion.count_documents(filtro, hint=hint) if hint else coleccion.count_documents(filtro)
    return etapas, n, time.perf_counter() - t0


def evidenciar(fuente: str) -> list[dict]:
    cfg = load_config()
    db = get_database()
    coleccion = db[cfg["database"]["collections"][f"edificios_{fuente}"]]
    cod, nombre, poligono = _municipio_prueba(cfg)

    consultas = {
        "geoWithin(centroide)": {"centroide": {"$geoWithin": {"$geometry": poligono}}},
        "geoIntersects(geometry)": {"geometry": {"$geoIntersects": {"$geometry": poligono}}},
    }
    filas = []
    for nombre_q, filtro in consultas.items():
        etapas, n, seg = _medir(coleccion, filtro)
        if "IXSCAN" not in etapas or "COLLSCAN" in etapas:
            raise AssertionError(f"{fuente} {nombre_q}: no usó el índice ({etapas})")
        filas.append({"fuente": fuente, "consulta": nombre_q, "plan": "IXSCAN",
                      "resultados": n, "segundos": round(seg, 2)})
        print(f"[evidencia] {fuente} {nombre_q}: {etapas} -> {n:,} en {seg:.2f} s")

    # Contraste: la misma consulta forzando recorrido completo.
    filtro = consultas["geoWithin(centroide)"]
    try:
        t0 = time.perf_counter()
        n_manual = sum(1 for _ in coleccion.find(filtro, {"_id": 1}).hint([("$natural", 1)]))
        seg_scan = time.perf_counter() - t0
        filas.append({"fuente": fuente, "consulta": "geoWithin(centroide) sin índice",
                      "plan": "COLLSCAN", "resultados": n_manual,
                      "segundos": round(seg_scan, 2)})
        print(f"[evidencia] {fuente} sin índice (COLLSCAN): {n_manual:,} en {seg_scan:.2f} s")
    except Exception as e:  # $geoWithin con $natural puede no estar soportado
        print(f"[evidencia] contraste COLLSCAN no disponible: {e}")

    stats = db.command("collStats", coleccion.name)
    print(f"[evidencia] {fuente}: {stats['count']:,} docs, datos {stats['size']/1e6:.0f} MB, "
          f"índices {stats['totalIndexSize']/1e6:.0f} MB "
          f"({', '.join(f'{k}={v/1e6:.0f}MB' for k, v in stats['indexSizes'].items())})")
    print(f"[evidencia] municipio de prueba: {nombre} ({cod})")
    return filas


if __name__ == "__main__":
    fuentes = sys.argv[1:] or ["google", "microsoft"]
    salida = ROOT / "data/processed/evidencia_edificios.csv"
    # Conserva las filas de las fuentes que no se vuelven a medir.
    previas = []
    if salida.exists():
        with open(salida, newline="", encoding="utf-8") as fh:
            previas = [r for r in csv.DictReader(fh) if r["fuente"] not in fuentes]
    nuevas = []
    for f in fuentes:
        nuevas += evidenciar(f)
    filas = sorted(previas + nuevas, key=lambda r: r["fuente"])
    with open(salida, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(nuevas[0]))
        w.writeheader()
        w.writerows(filas)
    print(f"[evidencia] guardado en {salida}")
