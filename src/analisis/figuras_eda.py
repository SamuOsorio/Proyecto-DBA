"""Figuras del EDA para el informe (Entrega 3). Se generan por script, no a mano.

    python -m src.analisis.figuras_eda

Lee data/processed/edificios_{google,microsoft}.parquet y municipios_pdet.geojson,
y escribe las cuatro figuras en Entrega 3/img/. Solo usa las columnas de centroide
y área, así que no decodifica la geometría WKB.
"""
from __future__ import annotations

import json
import unicodedata

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.analisis.estilo import COLORES, NOMBRE_COMPLETO, guardar, miles
from src.common.config import ROOT

PROCESADOS = ROOT / "data" / "processed"
COLUMNAS = ["centroide_lon", "centroide_lat", "area_m2"]
FUENTES = {"Google": "edificios_google.parquet", "Microsoft": "edificios_microsoft.parquet"}
SIN_EDIFICIOS_GOOGLE = ["Murindó", "Vigía del Fuerte", "Medio San Juan", "Nóvita", "Bojayá"]


def sin_acentos(texto: str) -> str:
    """Nombre en mayúsculas sin tildes, para cruzar 'Bojayá' con 'BOJAYA'."""
    nfd = unicodedata.normalize("NFKD", texto.upper())
    return "".join(c for c in nfd if not unicodedata.combining(c))


def cargar_fuentes() -> dict[str, pd.DataFrame]:
    cols = COLUMNAS + ["area_m2_fuente", "confianza"]
    out = {}
    for nombre, archivo in FUENTES.items():
        df = pd.read_parquet(PROCESADOS / archivo, columns=[c for c in cols])
        out[nombre] = df
    return out


def cargar_municipios() -> gpd.GeoDataFrame:
    with open(PROCESADOS / "municipios_pdet.geojson", encoding="utf-8") as f:
        feats = json.load(f)["features"]
    gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
    gdf["nombre"] = [f["properties"]["nombre"] for f in feats]
    gdf["subregion"] = [f["properties"]["subregion_pdet"]["nombre"] for f in feats]
    gdf["_id"] = [f["properties"]["_id"] for f in feats]
    return gdf


def puntos(df: pd.DataFrame) -> gpd.GeoSeries:
    return gpd.GeoSeries(gpd.points_from_xy(df["centroide_lon"], df["centroide_lat"]), crs=4326)


MINUSCULAS = {"y", "de", "del", "la", "las", "los", "el", "en"}


def nombre_subregion(texto: str) -> str:
    """'SIERRA NEVADA - PERIJÁ' -> 'Sierra Nevada - Perijá' (conectores en minúscula)."""
    palabras = texto.lower().split(" ")
    return " ".join(p if (i and p in MINUSCULAS) else p[:1].upper() + p[1:]
                    for i, p in enumerate(palabras))


def figura_subregion(fuentes, municipios):
    conteos = {}
    for nombre, df in fuentes.items():
        pts = gpd.GeoDataFrame(geometry=puntos(df), crs=4326)
        j = gpd.sjoin(pts, municipios[["subregion", "geometry"]], how="inner", predicate="within")
        conteos[nombre] = j.groupby("subregion").size()
    tabla = pd.DataFrame(conteos).fillna(0).astype(int)
    tabla = tabla.sort_values("Google")
    tabla.index = [nombre_subregion(s) for s in tabla.index]

    fig, eje = plt.subplots(figsize=(8, 7))
    alto = 0.4
    y = np.arange(len(tabla))
    for i, nombre in enumerate(["Google", "Microsoft"]):
        eje.barh(y + (i - 0.5) * alto, tabla[nombre], height=alto,
                 color=COLORES[nombre], label=NOMBRE_COMPLETO[nombre])
    eje.set_yticks(y)
    eje.set_yticklabels(tabla.index, fontsize=9)
    eje.xaxis.set_major_formatter(miles)
    eje.set_xlabel("Número de edificios")
    eje.legend(loc="lower right", frameon=False)
    eje.grid(axis="x", linewidth=0.4, alpha=0.5)
    fig.tight_layout()
    return guardar(fig, "eda_subregion")


def figura_comparacion(fuentes):
    g = fuentes["Google"].dropna(subset=["area_m2_fuente"])
    dif_pct = (g["area_m2"] - g["area_m2_fuente"]) / g["area_m2_fuente"] * 100

    fig, ejes = plt.subplots(1, 3, figsize=(8.5, 3.4))

    ejes[0].hist(dif_pct.clip(-1, 1), bins=200, color=COLORES["Google"])
    ejes[0].axvline(0, color="black", linewidth=0.8)
    ejes[0].set_xlabel("Diferencia (%)")
    ejes[0].set_ylabel("Edificios")
    ejes[0].yaxis.set_major_formatter(miles)
    ejes[0].set_title("Nuestra área frente a Google")

    muestra = g.sample(200_000, random_state=42)
    hb = ejes[1].hexbin(muestra["area_m2_fuente"], muestra["area_m2"], gridsize=60,
                        xscale="log", yscale="log", bins="log", mincnt=1, cmap="Blues")
    lim = [1, 1e5]
    ejes[1].plot(lim, lim, color="red", linewidth=0.9, label="1:1")
    ejes[1].set_xlabel("Área reportada por Google (m²)")
    ejes[1].set_ylabel("Área calculada (m²)")
    ejes[1].set_title("Área por edificio")
    ejes[1].legend(frameon=False, loc="upper left")
    cb = fig.colorbar(hb, ax=ejes[1], shrink=0.6, pad=0.04, aspect=18)
    cb.set_label("Edificios (log)", fontsize=8)
    cb.ax.tick_params(labelsize=7)

    totales = {n: df["area_m2"].sum() / 1e6 for n, df in fuentes.items()}
    ejes[2].bar(list(totales), list(totales.values()), color=[COLORES[n] for n in totales])
    for i, v in enumerate(totales.values()):
        ejes[2].text(i, v, f"{v:,.1f}".replace(",", "."), ha="center", va="bottom", fontsize=9)
    ejes[2].set_ylabel("Área total (km²)")
    ejes[2].set_ylim(0, max(totales.values()) * 1.15)
    ejes[2].set_title("Área total por fuente")

    fig.tight_layout()
    fig.subplots_adjust(wspace=0.85)
    return guardar(fig, "eda_comparacion")


def figura_confianza_area(fuentes):
    fig, ejes = plt.subplots(1, 2, figsize=(8, 3.4))
    bins = np.logspace(0, 4.5, 90)
    for nombre, df in fuentes.items():
        ejes[0].hist(df["area_m2"].clip(lower=1), bins=bins, density=True,
                     histtype="step", linewidth=1.6, color=COLORES[nombre], label=nombre)
        ejes[0].axvline(df["area_m2"].median(), color=COLORES[nombre], linestyle="--", linewidth=0.9)
    ejes[0].set_xscale("log")
    ejes[0].set_xticks([10, 100, 1000])
    ejes[0].set_xticklabels(["10", "100", "1.000"])
    ejes[0].set_xlabel("Área de la huella (m², escala log)")
    ejes[0].set_ylabel("Proporción de edificios")
    ejes[0].set_title("Distribución de áreas (líneas: medianas)")
    ejes[0].legend(frameon=False)

    conf = fuentes["Google"]["confianza"].dropna()
    ejes[1].hist(conf, bins=70, color=COLORES["Google"])
    for umbral in (0.70, 0.75):
        ejes[1].axvline(umbral, color="black", linestyle=":", linewidth=1)
        ejes[1].text(umbral, ejes[1].get_ylim()[1] * 0.92, f" {umbral:.2f}", fontsize=8)
    ejes[1].set_xlabel("Confianza del modelo (Google)")
    ejes[1].set_ylabel("Edificios")
    ejes[1].yaxis.set_major_formatter(miles)
    ejes[1].set_title("Confianza de Google")

    fig.tight_layout()
    return guardar(fig, "eda_confianza_area")


def figura_mapa(fuentes, municipios):
    fig, ejes = plt.subplots(1, 2, figsize=(8, 4.6))
    subregiones = municipios.dissolve(by="subregion")
    sin = municipios[municipios["nombre"].map(sin_acentos).isin([sin_acentos(n) for n in SIN_EDIFICIOS_GOOGLE])]
    sin = sin.assign(orden=sin["nombre"].map(lambda n: SIN_EDIFICIOS_GOOGLE.index(
        next(x for x in SIN_EDIFICIOS_GOOGLE if sin_acentos(x) == sin_acentos(n)))))
    sin = sin.sort_values("orden")
    hexbins = []
    for eje, (nombre, df) in zip(ejes, fuentes.items()):
        p = puntos(df)
        hb = eje.hexbin(p.x, p.y, gridsize=120, bins="log", mincnt=1, cmap="magma")
        hexbins.append(hb)
        subregiones.boundary.plot(ax=eje, linewidth=0.35, color="white", alpha=0.6)
        eje.set_title(NOMBRE_COMPLETO[nombre], fontsize=10)
        eje.set_aspect("equal")
        eje.set_facecolor("black")
        eje.set_axis_off()
    vmax = max(float(np.nanmax(hb.get_array())) for hb in hexbins)
    for hb in hexbins:
        hb.set_clim(1, vmax)

    # municipios sin edificios de Google: contorno rojo y número en el mapa
    sin.boundary.plot(ax=ejes[0], linewidth=1.6, color="#FF3B30")
    for i, (_, fila) in enumerate(sin.iterrows(), start=1):
        c = fila.geometry.representative_point()
        ejes[0].annotate(str(i), (c.x, c.y), fontsize=8, color="white", ha="center",
                         va="center", fontweight="bold",
                         bbox=dict(boxstyle="circle,pad=0.2", fc="#FF3B30", ec="none"))
    lista = "\n".join(f"{i}. {f['nombre'].title()}" for i, (_, f) in enumerate(sin.iterrows(), start=1))
    ejes[0].text(0.02, 0.02, "Sin edificios en Google:\n" + lista, transform=ejes[0].transAxes,
                 fontsize=7, color="white", va="bottom", ha="left",
                 bbox=dict(boxstyle="round,pad=0.3", fc="black", ec="#FF3B30", alpha=0.85))

    fig.subplots_adjust(bottom=0.2, wspace=0.05)
    cax = fig.add_axes([0.25, 0.08, 0.5, 0.03])
    cb = fig.colorbar(hexbins[1], cax=cax, orientation="horizontal")
    cb.set_label("Edificios por celda (escala log)")
    return guardar(fig, "eda_mapa_densidad")


def main() -> None:
    fuentes = cargar_fuentes()
    municipios = cargar_municipios()
    for f in (figura_subregion(fuentes, municipios),
              figura_comparacion(fuentes),
              figura_confianza_area(fuentes),
              figura_mapa(fuentes, municipios)):
        print("escrita:", f)


if __name__ == "__main__":
    main()
