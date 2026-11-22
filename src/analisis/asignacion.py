"""Asignación de edificios a municipios por centroide (semana 4).

Para cada uno de los 170 municipios hace un `updateMany` con `$geoWithin` sobre
`centroide` y filtro `cod_mpio: null`, en `edificios_google` y `edificios_microsoft`.
Como el filtro exige `cod_mpio` nulo, un edificio solo se asigna una vez: si su
centroide cae justo sobre el límite de dos municipios, gana el primero en el
recorrido (orden por código DANE).

Después cuenta los edificios que quedaron sin municipio y diagnostica por qué
(distancia al límite y si caen dentro del polígono según GeoPandas), y lo registra
todo en `bitacora_cargas` (etapa="asignacion", un documento por fuente).

Salidas en data/processed/: asignacion_municipios.csv, asignacion_resumen.csv,
asignacion_resumen.tex (tabla lista para el informe).

Uso:
  python -m src.analisis.asignacion              # asigna las dos fuentes
  python -m src.analisis.asignacion --reiniciar  # pone cod_mpio en null y asigna desde cero
  python -m src.analisis.asignacion google       # solo una fuente
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pymongo.errors import OperationFailure

from src.common.config import ROOT, load_config
from src.common.db import get_database

FUENTES = ("google", "microsoft")
INDICE_CENTROIDE = "centroide_2dsphere"
PROCESADOS = ROOT / "data" / "processed"
MAX_DIAGNOSTICO = 100_000  # centroides sin municipio que se analizan como máximo


def _colecciones(db, cfg: dict, fuente: str):
    c = cfg["database"]["collections"]
    return db[c["municipios"]], db[c[f"edificios_{fuente}"]]


def _actualizar(col, filtro: dict, cambios: dict, hint):
    """update_many con hint al índice del centroide; si el índice no existe, sigue sin hint."""
    if hint:
        try:
            return col.update_many(filtro, cambios, hint=hint), hint
        except OperationFailure as e:
            if "hint" not in str(e).lower():
                raise
            print(f"[asignacion] AVISO: el hint '{hint}' no sirvió ({e}). Se sigue sin hint.")
    return col.update_many(filtro, cambios), None


# ------------------------------------------------------------ asignación
def asignar_fuente(fuente: str, reiniciar: bool = False, usar_hint: bool = True) -> dict:
    cfg = load_config()
    db = get_database()
    mun, col = _colecciones(db, cfg, fuente)

    municipios = list(mun.find({}, {"nombre": 1, "geometry": 1}).sort("_id", 1))
    if not municipios:
        raise RuntimeError("La colección `municipios` está vacía. Corre antes `make municipios`.")
    total = col.count_documents({})
    if total == 0:
        raise RuntimeError(f"`edificios_{fuente}` está vacía. Corre antes `make edificios`.")

    if reiniciar:
        n = col.update_many({"cod_mpio": {"$ne": None}}, {"$set": {"cod_mpio": None}}).modified_count
        print(f"[asignacion] {fuente}: cod_mpio reiniciado en {n:,} documentos.")

    hint = INDICE_CENTROIDE if usar_hint else None
    filas = []
    t_total = time.perf_counter()
    for i, m in enumerate(municipios, 1):
        filtro = {"cod_mpio": None,
                  "centroide": {"$geoWithin": {"$geometry": m["geometry"]}}}
        t0 = time.perf_counter()
        res, hint = _actualizar(col, filtro, {"$set": {"cod_mpio": m["_id"]}}, hint)
        seg = time.perf_counter() - t0
        filas.append({"cod_mpio": m["_id"], "nombre": m.get("nombre"), "fuente": fuente,
                      "asignados": res.modified_count, "segundos": round(seg, 3)})
        if i % 10 == 0 or i == len(municipios):
            print(f"[asignacion] {fuente}: {i}/{len(municipios)} municipios, "
                  f"{sum(f['asignados'] for f in filas):,} asignados, "
                  f"{time.perf_counter() - t_total:.0f} s")
    segundos = time.perf_counter() - t_total

    sin_municipio = col.count_documents({"cod_mpio": None})
    return {"fuente": fuente, "total": total, "asignados": total - sin_municipio,
            "sin_municipio": sin_municipio, "segundos": segundos,
            "asignados_en_esta_corrida": sum(f["asignados"] for f in filas),
            "hint": hint, "municipios": len(municipios), "filas": filas}


# ------------------------------------------------- por qué quedan sin municipio
def _municipios_gdf(db, cfg: dict) -> gpd.GeoDataFrame:
    docs = list(db[cfg["database"]["collections"]["municipios"]].find({}, {"geometry": 1}))
    return gpd.GeoDataFrame(
        {"cod_mpio": [d["_id"] for d in docs]},
        geometry=[shapely.geometry.shape(d["geometry"]) for d in docs],
        crs=cfg["crs"]["almacenamiento"])


def diagnosticar_sin_municipio(fuente: str, max_docs: int = MAX_DIAGNOSTICO) -> dict:
    """Explica los edificios con cod_mpio nulo con evidencia medida con GeoPandas.

    Para cada centroide sin municipio mide (a) si cae dentro de algún polígono según
    GeoPandas (geometría plana en lon/lat, como el prefiltro de la semana 3) y
    (b) su distancia al límite municipal más cercano, en metros (EPSG:9377).
    MongoDB evalúa $geoWithin sobre la esfera (S2), con aristas geodésicas; GeoPandas
    usa aristas rectas en el plano. Un centroide cerca del límite puede quedar
    dentro en una y fuera en la otra.
    """
    cfg = load_config()
    db = get_database()
    _, col = _colecciones(db, cfg, fuente)
    n_sin = col.count_documents({"cod_mpio": None})
    if n_sin == 0:
        return {"sin_municipio": 0, "analizados": 0,
                "explicacion": "Todos los edificios quedaron asignados a un municipio."}

    docs = list(col.find({"cod_mpio": None}, {"centroide": 1}).limit(max_docs))
    lon = np.array([d["centroide"]["coordinates"][0] for d in docs])
    lat = np.array([d["centroide"]["coordinates"][1] for d in docs])
    crs_alm, crs_calc = cfg["crs"]["almacenamiento"], cfg["crs"]["calculo_areas"]

    mun = _municipios_gdf(db, cfg)
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lon, lat), crs=crs_alm)

    # (a) ¿dentro de algún polígono en el plano?
    unidos = gpd.sjoin(pts, mun[["geometry"]], predicate="within", how="inner")
    dentro_plano = pts.index.isin(unidos.index.unique())

    # (b) distancia al límite más cercano, en metros
    bordes = gpd.GeoDataFrame(geometry=mun.to_crs(crs_calc).boundary, crs=crs_calc)
    cerca = gpd.sjoin_nearest(pts.to_crs(crs_calc), bordes, distance_col="d_m")
    dist = cerca.groupby(level=0)["d_m"].min().reindex(pts.index).to_numpy()

    cortes = pd.cut(dist, bins=[-np.inf, 1, 10, 100, np.inf],
                    labels=["hasta 1 m", "1 a 10 m", "10 a 100 m", "más de 100 m"])
    por_distancia = {k: int(v) for k, v in pd.Series(cortes).value_counts().sort_index().items()}

    n, n_dentro = len(docs), int(dentro_plano.sum())
    mediana, p95, maximo = (float(np.median(dist)), float(np.percentile(dist, 95)),
                            float(dist.max()))
    partes = []
    if n_dentro:
        partes.append(
            f"{n_dentro:,} de {n:,} ({100 * n_dentro / n:.1f} %) caen dentro de un polígono "
            "según GeoPandas (geometría plana) pero MongoDB los deja fuera: las aristas "
            "esféricas (S2) no coinciden con las planas.")
    if n - n_dentro:
        partes.append(
            f"{n - n_dentro:,} ya están fuera de todo polígono también en el plano: su "
            "centroide queda justo sobre el límite o fuera de él (el centroide almacenado "
            "se recalculó en EPSG:9377 y puede diferir del usado en el prefiltro).")
    partes.append(f"Distancia al límite: mediana {mediana:.2f} m, p95 {p95:.2f} m, máx. {maximo:.2f} m.")
    if n < n_sin:
        partes.append(f"(Se analizó una muestra de {n:,} de {n_sin:,}.)")
    return {"sin_municipio": n_sin, "analizados": n, "dentro_en_plano": n_dentro,
            "fuera_en_plano": n - n_dentro, "por_distancia": por_distancia,
            "mediana_m": round(mediana, 3), "p95_m": round(p95, 3), "max_m": round(maximo, 3),
            "explicacion": " ".join(partes)}


# ----------------------------------------------------------------- salida
def _tex(resumen: pd.DataFrame) -> str:
    def n(x): return f"{int(x):,}".replace(",", "\\,")
    cuerpo = "\n".join(
        f"{r.fuente.capitalize()} & {n(r.edificios)} & {n(r.asignados)} & {n(r.sin_municipio)} & "
        f"{str(round(r.pct_sin, 4)).replace('.', ',')}\\,\\% & {str(round(r.segundos, 1)).replace('.', ',')} \\\\"
        for r in resumen.itertuples())
    return ("\\begin{table}[H]\n\\centering\\small\n"
            "\\caption{Asignación de edificios a municipios por centroide.}\n\\label{tab:asignacion}\n"
            "\\begin{tabular}{@{}lrrrrr@{}}\n\\toprule\n"
            "\\textbf{Fuente} & \\textbf{Edificios} & \\textbf{Asignados} & \\textbf{Sin municipio} "
            "& \\textbf{\\% sin} & \\textbf{Tiempo (s)} \\\\\n\\midrule\n"
            f"{cuerpo}\n\\bottomrule\n\\end{{tabular}}\n\\end{{table}}\n")


def asignar_edificios(fuentes=FUENTES, reiniciar: bool = False, usar_hint: bool = True) -> list[dict]:
    cfg = load_config()
    db = get_database()
    bitacora = db[cfg["database"]["collections"]["bitacora_cargas"]]
    resultados, filas_mun = [], []

    for fuente in fuentes:
        inicio = datetime.now(timezone.utc)
        r = asignar_fuente(fuente, reiniciar=reiniciar, usar_hint=usar_hint)
        print(f"[asignacion] {fuente}: {r['sin_municipio']:,} sin municipio. Diagnosticando...")
        diag = diagnosticar_sin_municipio(fuente)
        print(f"[asignacion] {fuente}: {diag['explicacion']}")
        fin = datetime.now(timezone.utc)

        bitacora.insert_one({
            "fuente_id": fuente, "etapa": "asignacion", "inicio": inicio, "fin": fin,
            "registros_ok": r["asignados"], "registros_error": r["sin_municipio"],
            "parametros": {
                "metodo": "updateMany $geoWithin sobre centroide, filtro cod_mpio null",
                "hint": r["hint"], "municipios": r["municipios"],
                "reiniciado": reiniciar, "segundos": round(r["segundos"], 2),
                "asignados_en_esta_corrida": r["asignados_en_esta_corrida"],
                "sin_municipio_diagnostico": diag,
                "por_municipio": [{"cod_mpio": f["cod_mpio"], "asignados": f["asignados"],
                                   "segundos": f["segundos"]} for f in r["filas"]],
            },
        })
        r["diagnostico"] = diag
        filas_mun += r["filas"]
        resultados.append(r)

    PROCESADOS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(filas_mun).to_csv(PROCESADOS / "asignacion_municipios.csv", index=False, encoding="utf-8-sig")
    resumen = pd.DataFrame([{
        "fuente": r["fuente"], "edificios": r["total"], "asignados": r["asignados"],
        "sin_municipio": r["sin_municipio"], "pct_sin": 100 * r["sin_municipio"] / r["total"],
        "segundos": r["segundos"]} for r in resultados])
    resumen.to_csv(PROCESADOS / "asignacion_resumen.csv", index=False, encoding="utf-8-sig")
    (PROCESADOS / "asignacion_resumen.tex").write_text(_tex(resumen), encoding="utf-8")

    print("\n=== ASIGNACIÓN POR CENTROIDE ===")
    print(resumen.assign(pct_sin=resumen["pct_sin"].round(4), segundos=resumen["segundos"].round(1))
          .to_string(index=False))
    print(f"\nGuardado en {PROCESADOS} (asignacion_municipios.csv, asignacion_resumen.csv/.tex). "
          "Registrado en bitacora_cargas.")
    return resultados


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Asigna edificios a municipios por centroide")
    ap.add_argument("fuentes", nargs="*", help="google y/o microsoft (por defecto, las dos)")
    ap.add_argument("--reiniciar", action="store_true", help="pone cod_mpio en null antes de asignar")
    ap.add_argument("--sin-hint", action="store_true", help="no fuerza el índice centroide_2dsphere")
    a = ap.parse_args()
    malas = [f for f in a.fuentes if f not in FUENTES]
    if malas:
        ap.error(f"fuente desconocida: {malas}; usa {list(FUENTES)}")
    asignar_edificios(tuple(a.fuentes) or FUENTES, reiniciar=a.reiniciar, usar_hint=not a.sin_hint)
