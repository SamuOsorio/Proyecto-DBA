"""t05+t06 (Maria Camila): valida, repara y reproyecta las geometrías municipales.

Flujo:
  1. validar_y_reparar(): lee la capa que deja cruce.py (Jorge), revisa is_valid
     de cada municipio y repara las inválidas con shapely.make_valid.
  2. reproyectar_y_calcular_area(): calcula area_km2 en EPSG:9377 y reproyecta
     a WGS84 (EPSG:4326, orden [lon, lat]) para guardar en MongoDB.

Como run.py llama a cada paso sin pasarle datos, los pasos se comunican por
archivos en data/processed/ (las rutas se pueden cambiar en config.yaml):
  - entrada:     municipios.intermedio_cruce      (lo escribe cruce.py)
  - intermedio:  municipios.intermedio_validado   (lo escribe validar_y_reparar)
  - salida:      municipios.intermedio_geometria  (lo lee exportar.py)
También deja municipios.reporte_geometrias (CSV) como evidencia para el informe.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
import yaml
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

RAIZ = Path(__file__).resolve().parents[2]

RUTAS_POR_DEFECTO = {
    "intermedio_cruce": "data/processed/municipios_pdet_cruce.gpkg",
    "intermedio_validado": "data/processed/municipios_pdet_validado.gpkg",
    "intermedio_geometria": "data/processed/municipios_pdet_geometria.gpkg",
    "reporte_geometrias": "data/processed/reporte_geometrias.csv",
    "salida_geojson": "data/processed/municipios_pdet.geojson",
}

# CRS que se asume si la capa llega sin CRS (MGN: MAGNA-SIRGAS geográficas).
CRS_MGN_POR_DEFECTO = "EPSG:4686"

# Rectángulo de control para Colombia continental en WGS84 (lon, lat).
BBOX_COLOMBIA = (-80.0, -4.5, -66.0, 13.5)

# Rejilla de 1e-6 grados (unos 10 cm): reduce el tamaño del GeoJSON y
# shapely.set_precision garantiza que la geometría siga siendo válida.
PRECISION_GRADOS = 1e-6


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def cargar_config() -> dict:
    with open(RAIZ / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ruta(cfg: dict, clave: str) -> Path:
    return RAIZ / cfg.get("municipios", {}).get(clave, RUTAS_POR_DEFECTO[clave])


def solo_poligonos(geom):
    """Deja solo las partes poligonales (make_valid puede devolver
    GeometryCollection con líneas o puntos sueltos) y devuelve un
    Polygon o MultiPolygon, o None si no queda nada."""
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    partes = []
    for g in getattr(geom, "geoms", []):
        if isinstance(g, Polygon):
            partes.append(g)
        elif isinstance(g, MultiPolygon):
            partes.extend(g.geoms)
    if not partes:
        return None
    return partes[0] if len(partes) == 1 else MultiPolygon(partes)


def orientar_rfc7946(geom):
    """Anillo exterior antihorario e interiores horarios, como pide GeoJSON."""
    if isinstance(geom, Polygon):
        return orient(geom, sign=1.0)
    return MultiPolygon([orient(p, sign=1.0) for p in geom.geoms])


def reparar(geom):
    """Devuelve (geometría reparada, se_reparó)."""
    if geom.is_valid:
        return geom, False
    return solo_poligonos(shapely.make_valid(geom)), True


# ---------------------------------------------------------------------------
# t05: validar y reparar
# ---------------------------------------------------------------------------
def validar_y_reparar(gdf: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    cfg = cargar_config()
    if gdf is None:
        entrada = ruta(cfg, "intermedio_cruce")
        if not entrada.exists():
            raise FileNotFoundError(
                f"No existe {entrada}. cruce.py (Jorge) debe guardar ahí los "
                "municipios PDET cruzados con el MGN."
            )
        gdf = gpd.read_file(entrada)

    if gdf.crs is None:
        print(f"[geometria] La capa no trae CRS; se asume {CRS_MGN_POR_DEFECTO}.")
        gdf = gdf.set_crs(CRS_MGN_POR_DEFECTO)

    gdf = gdf.copy()
    gdf["calidad_valida"] = gdf.geometry.is_valid
    gdf["calidad_motivo"] = [
        "" if v else shapely.is_valid_reason(g)
        for g, v in zip(gdf.geometry, gdf["calidad_valida"])
    ]
    reparadas = [reparar(g) for g in gdf.geometry]
    gdf["geometry"] = [g for g, _ in reparadas]
    gdf["calidad_reparada"] = [r for _, r in reparadas]

    vacias = gdf.geometry.isna()
    if vacias.any():
        raise ValueError(f"{vacias.sum()} geometrías quedaron vacías al repararlas.")

    gdf = gdf.set_geometry("geometry")
    gdf.to_file(ruta(cfg, "intermedio_validado"), driver="GPKG")

    n, inval = len(gdf), int((~gdf["calidad_valida"]).sum())
    print(f"[geometria] {n} municipios revisados; {inval} inválidos reparados.")
    return gdf


# ---------------------------------------------------------------------------
# t06: reproyectar y calcular área
# ---------------------------------------------------------------------------
def reproyectar_y_calcular_area(gdf: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    cfg = cargar_config()
    crs_areas = cfg["crs"]["calculo_areas"]
    crs_guardar = cfg["crs"]["almacenamiento"]

    if gdf is None:
        gdf = gpd.read_file(ruta(cfg, "intermedio_validado"))

    # Área en la proyección plana oficial (metros) -> km2.
    gdf = gdf.copy()
    gdf["area_km2"] = gdf.to_crs(crs_areas).geometry.area / 1e6

    # GeoPandas reproyecta con always_xy=True, así que queda [lon, lat].
    gdf = gdf.to_crs(crs_guardar)

    # Ajuste de precisión, nueva validación (la reproyección puede crear
    # errores mínimos), orientación GeoJSON y conteo de vértices.
    geoms = []
    for i, g in enumerate(gdf.geometry):
        g = shapely.set_precision(g, PRECISION_GRADOS)
        g = shapely.remove_repeated_points(g)
        if not g.is_valid:
            g = solo_poligonos(shapely.make_valid(g))
            gdf.iloc[i, gdf.columns.get_loc("calidad_reparada")] = True
        geoms.append(orientar_rfc7946(solo_poligonos(g)))
    gdf["geometry"] = geoms
    gdf = gdf.set_geometry("geometry")
    gdf["calidad_n_vertices"] = shapely.get_num_coordinates(gdf.geometry.values)

    # Control: ¿las coordenadas quedaron en orden [lon, lat] dentro de Colombia?
    minx, miny, maxx, maxy = gdf.total_bounds
    bx0, by0, bx1, by1 = BBOX_COLOMBIA
    if not (bx0 <= minx and maxx <= bx1 and by0 <= miny and maxy <= by1):
        raise ValueError(
            f"Coordenadas fuera de Colombia {gdf.total_bounds}: revisar el CRS "
            "de entrada o si lon/lat quedaron invertidas."
        )
    if not gdf.geometry.is_valid.all():
        raise ValueError("Quedaron geometrías inválidas después de reproyectar.")

    gdf.to_file(ruta(cfg, "intermedio_geometria"), driver="GPKG")
    _escribir_reporte(gdf, cfg)
    return gdf


def _escribir_reporte(gdf: gpd.GeoDataFrame, cfg: dict) -> None:
    cols = [c for c in gdf.columns if c != "geometry"]
    gdf[cols].to_csv(ruta(cfg, "reporte_geometrias"), index=False, encoding="utf-8")
    resumen = pd.Series({
        "municipios": len(gdf),
        "validas_de_origen": int(gdf["calidad_valida"].sum()),
        "reparadas": int(gdf["calidad_reparada"].sum()),
        "area_total_km2": round(float(gdf["area_km2"].sum()), 1),
        "vertices_total": int(gdf["calidad_n_vertices"].sum()),
        "vertices_max": int(gdf["calidad_n_vertices"].max()),
    }, dtype=object)
    print("[geometria] Resumen:\n" + resumen.to_string())


if __name__ == "__main__":
    validar_y_reparar()
    reproyectar_y_calcular_area()
