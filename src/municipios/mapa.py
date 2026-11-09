"""t04 (Jose Eduardo): mapa de control de los 170 municipios PDET.

Debe:
  - Leer el GeoJSON que exporta exportar.py (depende de t08, Maria Camila).
  - Graficar los 170 municipios sobre el mapa de Colombia (GeoPandas/matplotlib)
    como evidencia visual para el informe.
"""
import json

import geopandas as gpd
import matplotlib.pyplot as plt

from src.common.config import ROOT
from src.municipios.geometria import cargar_config, ruta

SALIDA_PNG = ROOT / "docs" / "mapa_control_municipios.png"


def generar_mapa_control() -> gpd.GeoDataFrame:
    cfg = cargar_config()
    with open(ruta(cfg, "salida_geojson"), encoding="utf-8") as f:
        features = json.load(f)["features"]

    # Las propiedades quedan en columnas planas; la subregión va como nombre.
    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    gdf["subregion"] = [f["properties"]["subregion_pdet"]["nombre"] for f in features]
    gdf["municipio"] = [f["properties"]["nombre"] for f in features]

    fig, ax = plt.subplots(figsize=(8, 10))
    subregiones = sorted(gdf["subregion"].unique())
    colores = plt.get_cmap("tab20")
    for i, nombre in enumerate(subregiones):
        gdf[gdf["subregion"] == nombre].plot(
            ax=ax, color=colores(i % 20), edgecolor="white", linewidth=0.2,
            label=nombre.title(),
        )
    ax.set_title(f"Municipios PDET: {len(gdf)} municipios en {len(subregiones)} subregiones")
    ax.set_axis_off()
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=7, frameon=False)

    SALIDA_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(SALIDA_PNG, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"[mapa] {len(gdf)} municipios -> {SALIDA_PNG}")
    return gdf


if __name__ == "__main__":
    generar_mapa_control()
