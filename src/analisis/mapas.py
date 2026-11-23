"""Mapas de resultados por municipio (semana 4, Maria Camila).

Genera tres mapas en `Entrega 4/img/`:

  mapa_area_fuentes.png   área de techos por municipio, un panel por fuente,
                          con las MISMAS clases en los dos (quintiles calculados
                          sobre las dos fuentes juntas) para poder compararlos.
  mapa_diferencia.png     índice D = (A_G - A_M) / (A_G + A_M), escala divergente
                          centrada en 0 (azul = más área en Google, naranja = más
                          área en Microsoft, gris = coinciden).
  mapa_pct_techos.png     % de la superficie municipal cubierta por techos
                          (escenario base, promedio de las dos fuentes).

No necesita la base de datos: lee los dos archivos versionados en el repo,
`data/processed/municipios_pdet.geojson` (límites) y
`data/processed/resultados_municipio.csv` (lo que exporta `exportar.py`).
Escenario base: Google con el umbral por defecto de config.yaml y Microsoft.

Uso:
  python -m src.analisis.mapas
"""
from __future__ import annotations

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch

from src.analisis.estilo import NOMBRE_COMPLETO, guardar
from src.common.config import ROOT, load_config

# Secuencial de un solo tono (verde) para magnitudes: no se confunde con el
# azul de Google ni el naranja de Microsoft, que identifican fuentes.
SECUENCIAL = ["#dcefdc", "#a9d8a9", "#6fbb72", "#3a9446", "#1b6b2c"]
# Divergente, de D negativo a positivo: naranja (más área en Microsoft) <->
# gris neutro <-> azul (más área en Google), los colores de cada fuente.
DIVERGENTE = ["#c4501f", "#f3b08f", "#e6e5e1", "#86b6ef", "#1c5cab"]
CORTES_D = [-1.0001, -0.3, -0.1, 0.1, 0.3, 1.0001]
ETIQUETAS_D = ["Microsoft mucho mayor (D < −0,3)", "Microsoft mayor (−0,3 a −0,1)",
               "Coinciden (−0,1 a 0,1)", "Google mayor (0,1 a 0,3)",
               "Google mucho mayor (D > 0,3)"]
SIN_DATO = "#d9d9d9"
BORDE = "#ffffff"


# ------------------------------------------------------------------ datos
def num(x: float, nd: int = 0) -> str:
    """Número con coma decimal y punto de miles: 1234.5 -> '1.234,5'."""
    s = f"{x:,.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def cargar(cfg: dict | None = None) -> gpd.GeoDataFrame:
    """Municipios con área de techos (ha) por fuente, D y % de techos, escenario base."""
    cfg = cfg or load_config()
    base = float(cfg["edificios"]["umbral_confianza_google_default"])
    res = pd.read_csv(ROOT / cfg["analisis"]["salida_csv"]["municipio"],
                      dtype={"cod_mpio": str}, encoding="utf-8-sig")
    res = res[((res.fuente == "google") & np.isclose(res.umbral.fillna(-1), base))
              | ((res.fuente == "microsoft") & res.umbral.isna())]
    if res.groupby("fuente").size().reindex(["google", "microsoft"]).fillna(0).ne(170).any():
        raise ValueError("resultados_municipio.csv no tiene 170 municipios por fuente en el "
                         "escenario base. Corre antes `python -m src.analisis.exportar`.")

    w = res.pivot(index="cod_mpio", columns="fuente",
                  values=["area_total_m2", "n_edificios", "pct_techos"])
    w.columns = [f"{m}_{f}" for m, f in w.columns]
    w = w.reset_index()
    w["ha_google"] = w.area_total_m2_google / 1e4
    w["ha_microsoft"] = w.area_total_m2_microsoft / 1e4
    suma = w.area_total_m2_google + w.area_total_m2_microsoft
    w["D"] = np.where(suma > 0, (w.area_total_m2_google - w.area_total_m2_microsoft) / suma, np.nan)
    w["pct_techos"] = (w.pct_techos_google + w.pct_techos_microsoft) / 2

    mun = gpd.read_file(ROOT / cfg["municipios"]["salida_geojson"])
    mun = mun.rename(columns={"_id": "cod_mpio"})
    mun["subregion_id"] = mun["subregion_pdet"].map(
        lambda s: s["id"] if isinstance(s, dict) else None)
    gdf = mun.merge(w, on="cod_mpio", how="left", validate="one_to_one")
    if gdf.D.isna().all():
        raise ValueError("No cruzó ningún municipio entre el GeoJSON y el CSV.")
    return gdf.to_crs(cfg["crs"]["calculo_areas"])  # proyección plana para dibujar


def clases_comunes(gdf: gpd.GeoDataFrame, k: int = 5) -> np.ndarray:
    """Quintiles del área (ha) calculados sobre las dos fuentes juntas, sin ceros."""
    v = pd.concat([gdf.ha_google, gdf.ha_microsoft])
    v = v[v > 0]
    cortes = np.quantile(v, np.linspace(0, 1, k + 1))
    cortes[0], cortes[-1] = 0, v.max() * 1.0001
    return cortes


# ----------------------------------------------------------------- dibujo
def _contorno(ax, gdf):
    """Contorno de las 16 subregiones sobre los municipios."""
    gdf.dissolve(by="subregion_id").boundary.plot(ax=ax, color="#4a4a4a", linewidth=0.6)


def _escala(ax, km: int = 200):
    """Barra de escala simple (el mapa está en EPSG:9377, en metros)."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    x, y = x0 + 0.05 * (x1 - x0), y0 + 0.05 * (y1 - y0)
    ax.plot([x, x + km * 1000], [y, y], color="#333333", linewidth=2, solid_capstyle="butt")
    ax.text(x + km * 500, y + 0.015 * (y1 - y0), f"{km} km", ha="center", va="bottom",
            fontsize=8, color="#333333")


def _limpiar(ax):
    ax.set_axis_off()
    ax.set_aspect("equal")


def _etiquetas_clases(cortes: np.ndarray) -> list[str]:
    etiquetas = []
    for i in range(len(cortes) - 1):
        a, b = cortes[i], cortes[i + 1]
        nd = 1 if b < 10 else 0
        etiquetas.append(f"{num(a, nd)} – {num(b, nd)} ha")
    return etiquetas


def mapa_area_fuentes(gdf: gpd.GeoDataFrame, cortes: np.ndarray):
    cmap = ListedColormap(SECUENCIAL)
    norm = BoundaryNorm(cortes, cmap.N)
    fig, axes = plt.subplots(1, 2, figsize=(8, 5.2))
    for ax, fuente in zip(axes, ("google", "microsoft")):
        col = f"ha_{fuente}"
        con = gdf[gdf[col] > 0]
        sin = gdf[~(gdf[col] > 0)]
        con.plot(column=col, cmap=cmap, norm=norm, ax=ax, edgecolor=BORDE, linewidth=0.25)
        if len(sin):
            sin.plot(ax=ax, color=SIN_DATO, edgecolor="#8a8a8a", hatch="////", linewidth=0.4)
        _contorno(ax, gdf)
        _limpiar(ax)
        nombre = NOMBRE_COMPLETO["Google" if fuente == "google" else "Microsoft"]
        total = gdf[col].sum() / 100  # ha -> km²
        ax.set_title(f"{nombre}\n{num(total, 1)} km² en total", fontsize=10, color="#222222")
    _escala(axes[0])
    handles = [Patch(facecolor=c, edgecolor="#bbbbbb", label=e)
               for c, e in zip(SECUENCIAL, _etiquetas_clases(cortes))]
    handles.append(Patch(facecolor=SIN_DATO, edgecolor="#8a8a8a", hatch="////",
                         label="Sin edificios en la fuente"))
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False,
               title="Área de techos por municipio (mismas clases en los dos mapas)",
               title_fontsize=9, fontsize=8.5)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.9, bottom=0.2, wspace=0.02)
    return fig


def mapa_diferencia(gdf: gpd.GeoDataFrame):
    cmap = ListedColormap(DIVERGENTE)
    norm = BoundaryNorm(CORTES_D, cmap.N)
    fig, ax = plt.subplots(figsize=(7, 7.4))
    sin_google = gdf.n_edificios_google.fillna(0) == 0
    gdf[~sin_google].plot(column="D", cmap=cmap, norm=norm, ax=ax,
                          edgecolor=BORDE, linewidth=0.25)
    gdf[sin_google].plot(ax=ax, color=SIN_DATO, edgecolor="#8a8a8a", hatch="////", linewidth=0.4)
    _contorno(ax, gdf)
    _limpiar(ax)

    _escala(ax)
    conteo = [int(((gdf.D >= a) & (gdf.D < b) & ~sin_google).sum())
              for a, b in zip(CORTES_D[:-1], CORTES_D[1:])]
    handles = [Patch(facecolor=c, edgecolor="#bbbbbb", label=f"{e}: {n} mpio{'' if n == 1 else 's'}.")
               for c, e, n in zip(DIVERGENTE, ETIQUETAS_D, conteo)]
    handles.append(Patch(facecolor=SIN_DATO, edgecolor="#8a8a8a", hatch="////",
                         label=f"Sin edificios en Google (D = −1): {int(sin_google.sum())} mpios."))
    fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False, fontsize=8.5,
               title="Índice de diferencia D = (A_G − A_M) / (A_G + A_M)", title_fontsize=9)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.17)
    return fig


def mapa_pct_techos(gdf: gpd.GeoDataFrame):
    v = gdf.pct_techos
    cortes = np.quantile(v, np.linspace(0, 1, 6))
    cortes[0], cortes[-1] = 0, v.max() * 1.0001
    cmap = ListedColormap(SECUENCIAL)
    norm = BoundaryNorm(cortes, cmap.N)
    fig, ax = plt.subplots(figsize=(7, 7))
    gdf.plot(column="pct_techos", cmap=cmap, norm=norm, ax=ax, edgecolor=BORDE, linewidth=0.25)
    _contorno(ax, gdf)
    _limpiar(ax)
    _escala(ax)
    etiquetas = [f"{num(a, 3)} – {num(b, 3)} %" for a, b in zip(cortes[:-1], cortes[1:])]
    handles = [Patch(facecolor=c, edgecolor="#bbbbbb", label=e)
               for c, e in zip(SECUENCIAL, etiquetas)]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=8.5,
               title="% de la superficie del municipio cubierta por techos "
                     "(promedio de las dos fuentes)", title_fontsize=9)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.14)
    return fig


# --------------------------------------------------------------- principal
def generar_mapas() -> list:
    cfg = load_config()
    carpeta = ROOT / cfg["analisis"]["carpeta_informe"] / "img"
    gdf = cargar(cfg)
    cortes = clases_comunes(gdf)
    rutas = [guardar(mapa_area_fuentes(gdf, cortes), "mapa_area_fuentes", carpeta),
             guardar(mapa_diferencia(gdf), "mapa_diferencia", carpeta),
             guardar(mapa_pct_techos(gdf), "mapa_pct_techos", carpeta)]
    print("[mapas] clases comunes (ha):", " | ".join(num(c, 1) for c in cortes))
    print(f"[mapas] municipios con |D| > 0,3: {int((gdf.D.abs() > 0.3).sum())} "
          f"(de ellos {int((gdf.n_edificios_google == 0).sum())} sin edificios en Google)")
    for r in rutas:
        print(f"[mapas] escrito {r.relative_to(ROOT)}")
    return rutas


if __name__ == "__main__":
    generar_mapas()
