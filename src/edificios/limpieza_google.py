"""Prefiltro, limpieza, exportación a Parquet y tabla de control de Google Open Buildings.

Tres pasos que se corren en orden (cada uno lee lo que dejó el anterior):

  1. prefiltrar_pdet()      Lee los CSV con DuckDB sin cargarlos completos en memoria.
                            Filtra por el rectángulo de cada municipio PDET y luego por
                            centroide dentro del polígono PDET.
                            -> data/processed/google_prefiltro/*.parquet
  2. limpiar_y_exportar()   Valida/repara geometrías, calcula centroide, area_m2 en
                            EPSG:9377 y geom_hash, quita duplicados y escribe
                            -> data/processed/edificios_google.parquet
  3. tabla_control_google() Archivos y GB descargados, registros en Colombia, tras el
                            filtro, inválidos, duplicados y tiempos.
                            -> data/processed/control_google.csv y control_google.tex

Uso:
  python -m src.edificios.limpieza_google            # corre los tres pasos
  python -m src.edificios.limpieza_google prefiltro  # o uno solo: prefiltro | limpieza | control
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely import STRtree

from src.common.config import ROOT, load_config
from src.municipios.cruce import leer_mgn, leer_pdet

PROCESADOS = ROOT / "data" / "processed"
DIR_PREFILTRO = PROCESADOS / "google_prefiltro"
DIR_LIMPIO = PROCESADOS / "google_limpio"
SALIDA = PROCESADOS / "edificios_google.parquet"
STATS = PROCESADOS / "google_stats.json"
FUENTE_ID = "google"

# --- Contrato de edificios_google.parquet (diccionario de datos, Entrega 1 sec. 5) ---
# geometry        BLOB (WKB)  Polygon en EPSG:4326
# centroide_*     DOUBLE      centroide de la huella en EPSG:4326 (carga.py arma el GeoJSON Point)
# area_m2         DOUBLE      área en EPSG:9377
# area_m2_fuente  DOUBLE      area_in_meters de Google
# confianza       DOUBLE      confidence de Google (0,65 a 1,0)
# cod_mpio        VARCHAR     NULL en esta fase; se llena en la fase 4
# geom_hash       VARCHAR     MD5 de la geometría normalizada, para detectar duplicados
# (lote_id lo asigna carga.py al insertar; no se escribe aquí)
COLUMNAS = ["fuente_id", "geometry", "centroide_lon", "centroide_lat", "area_m2",
            "area_m2_fuente", "confianza", "cod_mpio", "geom_hash"]
GEO_METADATA = {"version": "1.0.0", "primary_column": "geometry", "columns": {
    "geometry": {"encoding": "WKB", "geometry_types": ["Polygon"]}}}  # sin crs = OGC:CRS84 (lon/lat)


# ---------------------------------------------------------------- utilidades
def _guardar_stats(bloque: str, datos: dict) -> None:
    PROCESADOS.mkdir(parents=True, exist_ok=True)
    todo = json.loads(STATS.read_text(encoding="utf-8")) if STATS.exists() else {}
    todo[bloque] = datos
    STATS.write_text(json.dumps(todo, ensure_ascii=False, indent=2), encoding="utf-8")


def _leer_stats() -> dict:
    return json.loads(STATS.read_text(encoding="utf-8")) if STATS.exists() else {}


def _a_parquet(df: pd.DataFrame, ruta: Path) -> None:
    con = duckdb.connect()
    con.register("t", df)
    con.execute(f"COPY t TO '{ruta.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def _leer_parquet(ruta: Path) -> pd.DataFrame:
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM read_parquet('{ruta.as_posix()}')").df()
    con.close()
    return df


def _vaciar(carpeta: Path) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    for f in carpeta.glob("*.parquet"):
        f.unlink()


def _zonas(cfg: dict):
    """Municipios PDET (EPSG:4326) y el polígono de Colombia (simplificado, solo para contar)."""
    mgn = leer_mgn(cfg).to_crs(cfg["crs"]["almacenamiento"])
    pdet = leer_pdet(cfg)
    pdet_geo = mgn[mgn["cod_mpio"].isin(set(pdet["cod_mpio"]))][["cod_mpio", "geometry"]]
    colombia = mgn.geometry.union_all().simplify(0.001)  # ~100 m; basta para contar registros
    return pdet_geo.reset_index(drop=True), colombia


# ============================================================ 1. PREFILTRO
def prefiltrar_pdet(filas_por_parte: int = 500_000) -> dict:
    cfg = load_config()
    origen = ROOT / cfg["fuentes"]["google_open_buildings"]["destino_local"]
    archivos = sorted(origen.glob("*_buildings.csv.gz"))
    if not archivos:
        raise FileNotFoundError(f"No hay *_buildings.csv.gz en {origen}. Corre antes descarga_google.py")

    pdet_geo, colombia = _zonas(cfg)
    arbol = STRtree(pdet_geo.geometry.values)
    cods = pdet_geo["cod_mpio"].to_numpy()
    shapely.prepare(colombia)
    cminx, cminy, cmaxx, cmaxy = colombia.bounds

    # Primer filtro, dentro de DuckDB: el rectángulo de cada municipio PDET.
    # Solo las filas que caen en algún rectángulo conservan el WKT (el resto va NULL
    # y no pesa); así no se mueve geometría que no se va a usar.
    cajas = pdet_geo.bounds
    en_caja = " OR ".join(
        f"(longitude BETWEEN {r.minx} AND {r.maxx} AND latitude BETWEEN {r.miny} AND {r.maxy})"
        for r in cajas.itertuples())

    _vaciar(DIR_PREFILTRO)
    st = {"archivos": 0, "en_rectangulo_colombia": 0, "en_colombia": 0,
          "en_rectangulo_municipios": 0, "tras_prefiltro": 0}
    t0 = time.perf_counter()

    for archivo in archivos:
        token = archivo.name.split("_")[0]
        con = duckdb.connect()
        ruta = archivo.as_posix().replace("'", "''")
        columnas = {r[0] for r in con.execute(
            f"DESCRIBE SELECT * FROM read_csv('{ruta}', header = true)").fetchall()}
        faltan = {"latitude", "longitude", "area_in_meters", "confidence", "geometry"} - columnas
        if faltan:
            raise ValueError(f"{archivo.name}: faltan columnas {faltan}")

        res = con.execute(f"""
            SELECT latitude AS lat, longitude AS lon,
                   area_in_meters AS area_fuente, confidence AS confianza,
                   CASE WHEN {en_caja} THEN geometry END AS wkt
            FROM read_csv('{ruta}', header = true)
            WHERE longitude BETWEEN {cminx} AND {cmaxx} AND latitude BETWEEN {cminy} AND {cmaxy}
        """)
        buffer, filas, k = [], 0, 0

        def volcar():
            nonlocal buffer, filas, k
            if buffer:
                _a_parquet(pd.concat(buffer, ignore_index=True), DIR_PREFILTRO / f"{token}_{k:04d}.parquet")
                buffer, filas, k = [], 0, k + 1

        while True:
            df = res.fetch_df_chunk(50)  # ~100 mil filas por vuelta: nunca el CSV completo
            if df is None or len(df) == 0:
                break
            st["en_rectangulo_colombia"] += len(df)
            st["en_colombia"] += int(shapely.contains_xy(
                colombia, df["lon"].to_numpy(), df["lat"].to_numpy()).sum())

            cand = df["wkt"].notna().to_numpy()
            st["en_rectangulo_municipios"] += int(cand.sum())
            if not cand.any():
                continue
            sub = df[cand]
            puntos = shapely.points(sub["lon"].to_numpy(), sub["lat"].to_numpy())
            # segundo filtro: centroide (lat/lon de Google) dentro del polígono PDET
            pi, gi = arbol.query(puntos, predicate="intersects")
            if len(pi) == 0:
                continue
            _, primero = np.unique(pi, return_index=True)  # punto en borde de dos municipios: el primero
            pi, gi = pi[primero], gi[primero]
            ok = sub.iloc[pi].copy()
            ok["cod_mpio_pdet"] = cods[gi]
            buffer.append(ok)
            filas += len(ok)
            st["tras_prefiltro"] += len(ok)
            if filas >= filas_por_parte:
                volcar()
        volcar()
        con.close()
        st["archivos"] += 1
        print(f"{archivo.name}: acumulado {st['en_colombia']:,} en Colombia, "
              f"{st['tras_prefiltro']:,} tras el prefiltro")

    st["segundos"] = round(time.perf_counter() - t0, 1)
    _guardar_stats("prefiltro", st)
    return st


# ============================================================ 2. LIMPIEZA
def _poligonos(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    if hasattr(g, "geoms"):
        return [p for sub in g.geoms for p in _poligonos(sub)]
    return []


def _mayor_poligono(g):
    polys = _poligonos(g)
    return max(polys, key=lambda p: p.area) if polys else None


def limpiar_y_exportar() -> dict:
    cfg = load_config()
    crs_alm, crs_calc = cfg["crs"]["almacenamiento"], cfg["crs"]["calculo_areas"]
    partes = sorted(DIR_PREFILTRO.glob("*.parquet"))
    if not partes:
        raise FileNotFoundError(f"No hay partes en {DIR_PREFILTRO}. Corre antes prefiltrar_pdet()")

    _vaciar(DIR_LIMPIO)
    vistos: set = set()
    st = {"entrada": 0, "wkt_ilegible": 0, "reparados": 0, "reducidos_a_poligono": 0,
          "sin_poligono": 0, "area_cero": 0, "descartados_geometria": 0,
          "duplicados": 0, "salida": 0}
    t0 = time.perf_counter()

    for parte in partes:
        df = _leer_parquet(parte)
        st["entrada"] += len(df)

        geoms = shapely.from_wkt(df["wkt"].to_numpy(), on_invalid="ignore")
        nulos = shapely.is_missing(geoms)
        st["wkt_ilegible"] += int(nulos.sum())

        # validar y reparar
        malas = ~nulos & ~shapely.is_valid(geoms)
        if malas.any():
            geoms[malas] = shapely.make_valid(geoms[malas])
            st["reparados"] += int(malas.sum())

        # el contrato pide Polygon: MultiPolygon/GeometryCollection -> el polígono más grande
        no_poly = ~nulos & (shapely.get_type_id(geoms) != 3)
        for i in np.flatnonzero(no_poly):
            geoms[i] = _mayor_poligono(geoms[i])
        st["reducidos_a_poligono"] += int(no_poly.sum())

        buenas = ~shapely.is_missing(geoms) & ~shapely.is_empty(geoms)
        st["sin_poligono"] += int((~buenas & ~nulos).sum())
        df, geoms = df[buenas], geoms[buenas]

        # centroide y área en el CRS plano oficial; el centroide vuelve a WGS84
        proy = gpd.GeoSeries(geoms, crs=crs_alm).to_crs(crs_calc)
        area = proy.area.to_numpy()
        con_area = area > 0
        st["area_cero"] += int((~con_area).sum())
        df, geoms, proy, area = df[con_area], geoms[con_area], proy[con_area], area[con_area]
        cent = proy.centroid.to_crs(crs_alm)

        # geom_hash: geometría normalizada y redondeada a ~1 cm (1e-7 grados)
        norm = shapely.normalize(shapely.set_precision(geoms, 1e-7))
        norm = np.where(shapely.is_empty(norm), shapely.normalize(geoms), norm)
        hashes = [hashlib.md5(w).hexdigest() for w in shapely.to_wkb(norm)]

        # duplicados: dentro de la parte y contra todas las anteriores (entre celdas S2)
        conservar = np.ones(len(hashes), dtype=bool)
        for i, h in enumerate(hashes):
            clave = int(h[:16], 16)
            if clave in vistos:
                conservar[i] = False
            else:
                vistos.add(clave)
        st["duplicados"] += int((~conservar).sum())

        out = pd.DataFrame({
            "fuente_id": FUENTE_ID,
            "geometry": shapely.to_wkb(geoms),
            "centroide_lon": cent.x.to_numpy(),
            "centroide_lat": cent.y.to_numpy(),
            "area_m2": area,
            "area_m2_fuente": df["area_fuente"].to_numpy(),
            "confianza": df["confianza"].to_numpy(),
            "geom_hash": hashes,
        })[conservar]
        st["salida"] += len(out)
        if len(out):
            _a_parquet(out, DIR_LIMPIO / parte.name)
        print(f"{parte.name}: {len(out):,} filas limpias (acumulado {st['salida']:,})")

    st["descartados_geometria"] = st["wkt_ilegible"] + st["sin_poligono"] + st["area_cero"]

    # un solo Parquet final, con metadatos GeoParquet para que GeoPandas lo lea como capa
    geo = json.dumps(GEO_METADATA).replace("'", "''")
    sql_final = f"""
        COPY (
            SELECT fuente_id, geometry, centroide_lon, centroide_lat, area_m2,
                   area_m2_fuente, confianza, CAST(NULL AS VARCHAR) AS cod_mpio, geom_hash
            FROM read_parquet('{DIR_LIMPIO.as_posix()}/*.parquet')
        ) TO '{SALIDA.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD{{kv}})
    """
    con = duckdb.connect()
    try:
        con.execute(sql_final.format(kv=", KV_METADATA {geo: '" + geo + "'}"))
    except duckdb.Error as e:
        print(f"AVISO: no pude escribir los metadatos GeoParquet ({e}); se escribe sin ellos.")
        con.execute(sql_final.format(kv=""))
    st["salida"] = con.execute(f"SELECT count(*) FROM read_parquet('{SALIDA.as_posix()}')").fetchone()[0]
    con.close()

    st["segundos"] = round(time.perf_counter() - t0, 1)
    _guardar_stats("limpieza", st)
    print(f"Escrito {SALIDA} ({st['salida']:,} edificios)")
    return st


# ====================================================== 3. TABLA DE CONTROL
def _fmt(valor, decimales: int = 0) -> str:
    if decimales:
        return f"{valor:,.{decimales}f}".replace(",", "\\,").replace(".", ",")
    return f"{int(round(valor)):,}".replace(",", "\\,")


def tabla_control_google() -> pd.DataFrame:
    cfg = load_config()
    origen = ROOT / cfg["fuentes"]["google_open_buildings"]["destino_local"]
    desc = json.loads((origen / "descarga_google.json").read_text(encoding="utf-8")) \
        if (origen / "descarga_google.json").exists() else {}
    st = _leer_stats()
    pre, lim = st.get("prefiltro", {}), st.get("limpieza", {})
    if not (desc or pre or lim):
        raise FileNotFoundError("No hay estadísticas todavía: corre antes descarga y prefiltro/limpieza.")

    filas = [
        ("Archivos descargados (celdas S2 nivel 4)", len(desc.get("archivos", [])), 0),
        ("Tamaño descargado (GB, comprimido)", desc.get("bytes_total", 0) / 1e9, 2),
        ("Tiempo de descarga (min)", desc.get("segundos_total", 0) / 60, 1),
        ("Registros en el rectángulo de Colombia", pre.get("en_rectangulo_colombia", 0), 0),
        ("Registros dentro de Colombia", pre.get("en_colombia", 0), 0),
        ("Registros tras el prefiltro PDET", pre.get("tras_prefiltro", 0), 0),
        ("Geometrías inválidas reparadas", lim.get("reparados", 0), 0),
        ("Registros descartados por geometría", lim.get("descartados_geometria", 0), 0),
        ("Duplicados eliminados", lim.get("duplicados", 0), 0),
        ("Edificios finales en edificios\\_google.parquet", lim.get("salida", 0), 0),
        ("Tiempo de prefiltro (min)", pre.get("segundos", 0) / 60, 1),
        ("Tiempo de limpieza y exportación (min)", lim.get("segundos", 0) / 60, 1),
    ]
    tabla = pd.DataFrame({
        "concepto": [c.replace("\\_", "_") for c, _, _ in filas],
        "valor": pd.Series([round(v, d) if d else int(round(v)) for _, v, d in filas], dtype=object),
    })
    PROCESADOS.mkdir(parents=True, exist_ok=True)
    tabla.to_csv(PROCESADOS / "control_google.csv", index=False, encoding="utf-8-sig")

    cuerpo = "\n".join(f"{c} & {_fmt(v, d)} \\\\" for c, v, d in filas)
    tex = ("\\begin{table}[H]\n\\centering\\small\n"
           "\\caption{Tabla de control de Google Open Buildings v3.}\n\\label{tab:control_google}\n"
           "\\begin{tabular}{@{}lr@{}}\n\\toprule\n\\textbf{Concepto} & \\textbf{Valor} \\\\\n\\midrule\n"
           f"{cuerpo}\n\\bottomrule\n\\end{{tabular}}\n\\end{{table}}\n")
    (PROCESADOS / "control_google.tex").write_text(tex, encoding="utf-8")

    print("\n=== TABLA DE CONTROL: GOOGLE OPEN BUILDINGS ===")
    print(tabla.to_string(index=False))
    print(f"\nGuardada en {PROCESADOS / 'control_google.csv'} y control_google.tex (para el informe)")
    return tabla


# ------------------------------------------------------------------- CLI
def main(paso: str = "todo") -> None:
    if paso in ("prefiltro", "todo"):
        prefiltrar_pdet()
    if paso in ("limpieza", "todo"):
        limpiar_y_exportar()
    if paso in ("control", "todo"):
        tabla_control_google()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Prefiltro, limpieza y control de Google Open Buildings")
    ap.add_argument("paso", nargs="?", default="todo",
                    choices=["prefiltro", "limpieza", "control", "todo"])
    main(ap.parse_args().paso)
