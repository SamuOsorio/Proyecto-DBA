"""Contrato del Parquet intermedio de edificios y limpieza compartida.

Google y Microsoft pasan por la misma función `limpiar_bloque`, así que los dos
Parquet salen con las mismas columnas y las mismas reglas de calidad:

  fuente_id, geometry (WKB, EPSG:4326, lon/lat), centroide_lon, centroide_lat,
  area_m2 (EPSG:9377), area_m2_fuente, confianza, geom_hash

`cod_mpio` y `lote_id` no van aquí: `lote_id` lo pone la carga y `cod_mpio` se
asigna en la semana 4 con $geoWithin sobre el centroide.
"""
from __future__ import annotations

import hashlib

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from pyproj import Transformer

from src.common.config import ROOT, load_config

SCHEMA = pa.schema([
    ("fuente_id", pa.string()),
    ("geometry", pa.binary()),
    ("centroide_lon", pa.float64()),
    ("centroide_lat", pa.float64()),
    ("area_m2", pa.float64()),
    ("area_m2_fuente", pa.float64()),
    ("confianza", pa.float64()),
    ("geom_hash", pa.string()),
])

ESTADISTICAS = ["leidos", "sin_geometria", "fuera_pdet", "dentro_pdet",
                "invalidos", "descartados", "conservados"]

_A_9377 = Transformer.from_crs("EPSG:4326", "EPSG:9377", always_xy=True)


def cargar_union_pdet(cfg: dict | None = None):
    """Unión de los 170 municipios PDET, preparada para consultas rápidas."""
    cfg = cfg or load_config()
    municipios = gpd.read_file(ROOT / cfg["municipios"]["salida_geojson"])
    union = shapely.union_all(municipios.geometry.values)
    shapely.prepare(union)
    return union


def _mayor_poligono(geom):
    """Parte poligonal más grande de una geometría (None si no hay)."""
    polis = [p for p in shapely.get_parts(geom)
             if p.geom_type == "Polygon" and not p.is_empty]
    return max(polis, key=lambda p: p.area) if polis else None


def _area_9377(geoms: np.ndarray) -> np.ndarray:
    proyectadas = shapely.transform(
        geoms, lambda c: np.column_stack(_A_9377.transform(c[:, 0], c[:, 1])))
    return shapely.area(proyectadas)


def limpiar_bloque(geoms, union, fuente_id: str, area_fuente=None, confianza=None):
    """Filtra a PDET, valida y calcula centroide, área y hash de un bloque.

    Devuelve (DataFrame con las columnas de SCHEMA, dict con estadísticas).
    El filtro es la regla del centroide: se conserva el edificio cuyo centroide
    cae dentro de la unión de los municipios PDET.
    """
    geoms = np.asarray(geoms, dtype=object)
    n = len(geoms)
    area_fuente = np.full(n, np.nan) if area_fuente is None else np.asarray(area_fuente, float)
    confianza = np.full(n, np.nan) if confianza is None else np.asarray(confianza, float)

    st = dict.fromkeys(ESTADISTICAS, 0)
    st["leidos"] = n
    presente = ~shapely.is_missing(geoms)
    st["sin_geometria"] = int(n - presente.sum())

    # 1) Filtro por centroide dentro de PDET (antes de gastar tiempo en lo demás)
    cx = np.full(n, np.nan)
    cy = np.full(n, np.nan)
    if presente.any():
        c = shapely.centroid(geoms[presente])
        cx[presente], cy[presente] = shapely.get_x(c), shapely.get_y(c)
    dentro = presente & ~np.isnan(cx)
    dentro[dentro] = shapely.contains_xy(union, cx[dentro], cy[dentro])
    st["dentro_pdet"] = int(dentro.sum())
    st["fuera_pdet"] = int(presente.sum() - dentro.sum())

    idx = np.flatnonzero(dentro)
    g = geoms[idx].copy()
    if len(g) == 0:
        return pd.DataFrame({c.name: [] for c in SCHEMA}), st

    # 2) Validez: reparar con make_valid y quedarse con partes poligonales
    invalida = ~shapely.is_valid(g)
    st["invalidos"] = int(invalida.sum())
    if invalida.any():
        g[invalida] = shapely.make_valid(g[invalida])
    for i in np.flatnonzero(shapely.get_type_id(g) != 3):  # 3 = Polygon
        g[i] = _mayor_poligono(g[i])
    bueno = ~shapely.is_missing(g)
    bueno[bueno] = ~shapely.is_empty(g[bueno])

    g, idx = g[bueno], idx[bueno]
    a = _area_9377(g)
    positiva = a > 0
    g, idx, a = g[positiva], idx[positiva], a[positiva]
    st["descartados"] = int(dentro.sum() - len(g))
    st["conservados"] = len(g)

    # 3) Orientación GeoJSON (exterior antihorario), centroide final y hash
    g = shapely.orient_polygons(g, exterior_cw=False)
    c = shapely.centroid(g)
    huellas = shapely.to_wkb(shapely.normalize(g))
    df = pd.DataFrame({
        "fuente_id": fuente_id,
        "geometry": shapely.to_wkb(g),
        "centroide_lon": shapely.get_x(c),
        "centroide_lat": shapely.get_y(c),
        "area_m2": a,
        "area_m2_fuente": area_fuente[idx],
        "confianza": confianza[idx],
        "geom_hash": [hashlib.sha1(w).hexdigest() for w in huellas],
    })
    return df, st


def escribir_parquet(df: pd.DataFrame, ruta) -> None:
    tabla = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    pq.write_table(tabla, ruta, compression="zstd")
