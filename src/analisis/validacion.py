"""Validación independiente de la asignación con GeoPandas (semana 4).

Toma una muestra de 10 municipios (grandes, pequeños, del Chocó y alguno de los que
no tienen edificios de Google) y, para cada fuente, recalcula cuántos edificios caen
en cada uno SIN usar MongoDB para asignar: lee los centroides de los Parquet y los
límites del GeoJSON del repo, y hace `sjoin(predicate="within")`. Luego compara con
lo que dejó la asignación en MongoDB (`cod_mpio`), con la diferencia por municipio
y cuántos edificios están solo en uno de los dos lados (comparando `geom_hash`).

Salidas en data/processed/: validacion_asignacion.csv y validacion_asignacion.tex.

Uso:  python -m src.analisis.validacion
"""
from __future__ import annotations

import sys
import unicodedata

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.common.config import ROOT, load_config
from src.common.db import get_database

FUENTES = ("google", "microsoft")
PROCESADOS = ROOT / "data" / "processed"
TAMANO_MUESTRA = 10


def _norm(texto: str) -> str:
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()


def _conteos_mongo(db, cfg: dict, fuente: str) -> dict[str, int]:
    col = db[cfg["database"]["collections"][f"edificios_{fuente}"]]
    canal = [{"$match": {"cod_mpio": {"$ne": None}}},
             {"$group": {"_id": "$cod_mpio", "n": {"$sum": 1}}}]
    return {d["_id"]: d["n"] for d in col.aggregate(canal, allowDiskUse=True)}


def _elegir_muestra(munis: gpd.GeoDataFrame, mongo: dict[str, dict[str, int]]) -> dict[str, str]:
    """cod_mpio -> categoría. 3 grandes, 3 pequeños, 2 del Chocó, 2 sin Google; se completa a 10."""
    elegidos: dict[str, str] = {}

    def tomar(codigos, k: int, categoria: str) -> None:
        nuevos = 0
        for cod in codigos:
            if nuevos == k:
                break
            if cod in elegidos:
                continue
            elegidos[cod] = categoria
            nuevos += 1

    por_area = munis.sort_values("area_km2", ascending=False)["_id"].tolist()
    tomar(por_area, 3, "grande")
    tomar(por_area[::-1], 3, "pequeño")
    choco = munis[munis["departamento"].map(_norm).str.contains("choco")]
    tomar(choco.sort_values("area_km2", ascending=False)["_id"].tolist(), 2, "Chocó")
    sin_google = sorted(c for c in munis["_id"] if mongo["google"].get(c, 0) == 0)
    tomar(sin_google, 2, "sin Google")
    if len(elegidos) < TAMANO_MUESTRA:  # completa con los de más edificios
        mas = sorted(munis["_id"], key=lambda c: -(mongo["google"].get(c, 0) + mongo["microsoft"].get(c, 0)))
        tomar(mas, TAMANO_MUESTRA - len(elegidos), "con más edificios")
    return elegidos


def _contar_geopandas(parquet, muestra: gpd.GeoDataFrame, crs: str) -> dict[str, set]:
    """geom_hash de los centroides del Parquet que caen 'within' de cada municipio de la muestra."""
    tabla = pq.read_table(parquet, columns=["centroide_lon", "centroide_lat", "geom_hash"])
    lon, lat = tabla["centroide_lon"].to_numpy(), tabla["centroide_lat"].to_numpy()
    x0, y0, x1, y1 = muestra.total_bounds
    mascara = (lon >= x0) & (lon <= x1) & (lat >= y0) & (lat <= y1)  # solo los candidatos
    pts = gpd.GeoDataFrame(
        {"geom_hash": tabla.filter(pa.array(mascara))["geom_hash"].to_pylist()},
        geometry=gpd.points_from_xy(lon[mascara], lat[mascara]), crs=crs)
    unidos = gpd.sjoin(pts, muestra[["_id", "geometry"]], predicate="within", how="inner")
    return {cod: set(g["geom_hash"]) for cod, g in unidos.groupby("_id")}


def _tex(tabla: pd.DataFrame) -> str:
    def esc(s): return str(s).replace("_", "\\_").replace("&", "\\&").replace("%", "\\%")
    def n(x): return f"{int(x):,}".replace(",", "\\,")
    cuerpo = "\n".join(
        f"{esc(r.municipio)} & {esc(r.categoria)} & {r.fuente.capitalize()} & {n(r.mongo)} & "
        f"{n(r.geopandas)} & {int(r.diferencia):+d} \\\\" for r in tabla.itertuples())
    return ("\\begin{table}[H]\n\\centering\\small\n"
            "\\caption{Validación: edificios por municipio en MongoDB frente a GeoPandas.}\n"
            "\\label{tab:validacion-asignacion}\n\\begin{tabular}{@{}lllrrr@{}}\n\\toprule\n"
            "\\textbf{Municipio} & \\textbf{Categoría} & \\textbf{Fuente} & \\textbf{MongoDB} & "
            "\\textbf{GeoPandas} & \\textbf{Dif.} \\\\\n\\midrule\n"
            f"{cuerpo}\n\\bottomrule\n\\end{{tabular}}\n\\end{{table}}\n")


def validar() -> pd.DataFrame:
    cfg = load_config()
    db = get_database()
    crs = cfg["crs"]["almacenamiento"]

    # Límites desde el GeoJSON del repo: independiente de MongoDB.
    munis = gpd.read_file(ROOT / cfg["municipios"]["salida_geojson"])
    mongo = {f: _conteos_mongo(db, cfg, f) for f in FUENTES}
    if not any(mongo[f] for f in FUENTES):
        sys.exit("Ningún edificio tiene cod_mpio. Corre antes: python -m src.analisis.asignacion")

    elegidos = _elegir_muestra(munis, mongo)
    muestra = munis[munis["_id"].isin(elegidos)].copy()
    print(f"Muestra de {len(muestra)} municipios: " + ", ".join(
        f"{r['nombre']} ({elegidos[r['_id']]})" for _, r in muestra.iterrows()))

    filas = []
    for fuente in FUENTES:
        parquet = ROOT / cfg["edificios"]["salida_parquet"][fuente]
        if not parquet.exists():
            print(f"AVISO: no existe {parquet}; se omite {fuente}.")
            continue
        print(f"[validacion] {fuente}: recalculando con GeoPandas...")
        gp = _contar_geopandas(parquet, muestra, crs)
        col = db[cfg["database"]["collections"][f"edificios_{fuente}"]]
        for _, m in muestra.iterrows():
            cod = m["_id"]
            hashes_mongo = {d["geom_hash"] for d in col.find({"cod_mpio": cod}, {"geom_hash": 1, "_id": 0})}
            hashes_gp = gp.get(cod, set())
            filas.append({
                "cod_mpio": cod, "municipio": m["nombre"], "departamento": m["departamento"],
                "area_km2": round(float(m["area_km2"]), 1), "categoria": elegidos[cod], "fuente": fuente,
                "mongo": len(hashes_mongo), "geopandas": len(hashes_gp),
                "diferencia": len(hashes_mongo) - len(hashes_gp),
                "solo_mongo": len(hashes_mongo - hashes_gp), "solo_geopandas": len(hashes_gp - hashes_mongo),
            })

    tabla = pd.DataFrame(filas)
    tabla["pct_dif"] = (100 * tabla["diferencia"].abs() / tabla[["mongo", "geopandas"]].max(axis=1).clip(lower=1)).round(4)
    tabla = tabla.sort_values(["fuente", "categoria", "cod_mpio"]).reset_index(drop=True)
    PROCESADOS.mkdir(parents=True, exist_ok=True)
    tabla.to_csv(PROCESADOS / "validacion_asignacion.csv", index=False, encoding="utf-8-sig")
    (PROCESADOS / "validacion_asignacion.tex").write_text(_tex(tabla), encoding="utf-8")

    print("\n=== VALIDACIÓN: MONGODB vs GEOPANDAS ===")
    print(tabla[["municipio", "categoria", "fuente", "mongo", "geopandas", "diferencia",
                 "solo_mongo", "solo_geopandas"]].to_string(index=False))
    for fuente, g in tabla.groupby("fuente"):
        print(f"\n{fuente}: Mongo {g['mongo'].sum():,} vs GeoPandas {g['geopandas'].sum():,} "
              f"(dif. neta {g['diferencia'].sum():+,}; {g['solo_mongo'].sum():,} solo en Mongo, "
              f"{g['solo_geopandas'].sum():,} solo en GeoPandas; dif. máxima por municipio "
              f"{g['pct_dif'].max():.4f} %)")
    print(f"\nGuardado en {PROCESADOS / 'validacion_asignacion.csv'} y validacion_asignacion.tex")
    return tabla


if __name__ == "__main__":
    validar()
