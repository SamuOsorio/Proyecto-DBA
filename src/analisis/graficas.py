"""Gráficas de la semana 4 para el informe de Entrega 4 (Jose Eduardo).

    python -m src.analisis.graficas

Lee los resultados que ya calculó agregacion.py y sensibilidad.py:
  - data/processed/resultados_municipio.csv (un renglón por municipio, fuente y umbral)
  - Entrega 4/sensibilidad.csv (un renglón por fuente y umbral)
y escribe las figuras en Entrega 4/img/. No vuelve a consultar MongoDB.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from src.analisis.estilo import COLORES, NOMBRE_COMPLETO, miles
from src.common.config import ROOT

CARPETA_IMG = ROOT / "Entrega 4" / "img"
UMBRAL_BASE = 0.65
# Nombres como se escriben en el informe, y desplazamiento de cada etiqueta para no encimarse.
NOMBRE_MUNICIPIO = {"CARMEN DEL DARIEN": "Carmen del Darién"}
DESPLAZAMIENTO = {"Condoto": (-55, 6), "Carmen del Darién": (8, 10), "Ricaurte": (8, -14), "López": (8, 4), "Sipí": (8, 4)}


def nombre_municipio(texto: str) -> str:
    if texto in NOMBRE_MUNICIPIO:
        return NOMBRE_MUNICIPIO[texto]
    minusculas = {"de", "del", "la", "las", "los", "y"}
    palabras = texto.lower().split(" ")
    return " ".join(p if (i and p in minusculas) else p[:1].upper() + p[1:] for i, p in enumerate(palabras))


def guardar(fig, nombre: str):
    CARPETA_IMG.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA_IMG / f"{nombre}.png"
    fig.savefig(ruta, bbox_inches="tight")
    plt.close(fig)
    return ruta


def figura_dispersion() -> object:
    """Área total por municipio: Google (umbral base) contra Microsoft."""
    res = pd.read_csv(ROOT / "data" / "processed" / "resultados_municipio.csv", encoding="utf-8-sig",
                      dtype={"cod_mpio": str})
    g = res[(res["fuente"] == "google") & (res["umbral"] == UMBRAL_BASE)]
    m = res[res["fuente"] == "microsoft"]
    cruce = g[["cod_mpio", "municipio", "area_total_m2"]].merge(
        m[["cod_mpio", "area_total_m2"]], on="cod_mpio", suffixes=("_g", "_m"))
    cruce = cruce[(cruce["area_total_m2_g"] > 0) & (cruce["area_total_m2_m"] > 0)].copy()
    cruce["razon"] = cruce["area_total_m2_g"] / cruce["area_total_m2_m"]
    lejanos = cruce.assign(dist=np.abs(np.log10(cruce["razon"]))).nlargest(5, "dist")

    fig, eje = plt.subplots(figsize=(8, 5.6))
    eje.scatter(cruce["area_total_m2_m"] / 1e3, cruce["area_total_m2_g"] / 1e3,
                s=14, alpha=0.7, color=COLORES["Google"], edgecolor="none")
    lim = [cruce[["area_total_m2_m", "area_total_m2_g"]].min().min() / 1e3 * 0.8,
           cruce[["area_total_m2_m", "area_total_m2_g"]].max().max() / 1e3 * 1.2]
    eje.plot(lim, lim, color="black", linewidth=0.9, linestyle="--", label="1:1")
    eje.set_xscale("log")
    eje.set_yscale("log")
    eje.set_xlim(lim)
    eje.set_ylim(lim)
    for _, f in lejanos.iterrows():
        nombre = nombre_municipio(f["municipio"])
        eje.annotate(nombre, (f["area_total_m2_m"] / 1e3, f["area_total_m2_g"] / 1e3),
                     xytext=DESPLAZAMIENTO.get(nombre, (6, 4)), textcoords="offset points", fontsize=8)
    eje.set_xlabel("Área total Microsoft (miles de m²)")
    eje.set_ylabel(f"Área total {NOMBRE_COMPLETO['Google']} (miles de m²)")
    sin_google = int(m["cod_mpio"].nunique() - cruce["cod_mpio"].nunique())
    eje.set_title(f"Área total por municipio PDET (n = {len(cruce)})")
    eje.text(0.99, 0.02, f"Se excluyen {sin_google} municipios sin edificios de Google.",
             transform=eje.transAxes, ha="right", fontsize=7, color="0.3")
    eje.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    return guardar(fig, "res_dispersion_municipio")


def figura_sensibilidad() -> object:
    """Edificios y área total de Google según el umbral, con Microsoft como referencia."""
    sens = pd.read_csv(ROOT / "Entrega 4" / "sensibilidad.csv", encoding="utf-8-sig")
    g = sens[sens["fuente"] == "google"].sort_values("umbral")
    m = sens[sens["fuente"] == "microsoft"].iloc[0]

    fig, ejes = plt.subplots(1, 2, figsize=(8, 3.6))
    paneles = [
        ("n_edificios", "Edificios", 1, miles),
        ("area_total_km2", "Área total (km²)", 1, None),
    ]
    for eje, (col, titulo, _, fmt) in zip(ejes, paneles):
        eje.plot(g["umbral"], g[col], marker="o", color=COLORES["Google"], label="Google")
        eje.axhline(m[col], color=COLORES["Microsoft"], linestyle="--", linewidth=1.2,
                    label="Microsoft (referencia)")
        for _, f in g.iterrows():
            eje.annotate(f"{f[col]:,.0f}" if fmt else f"{f[col]:.1f}", (f["umbral"], f[col]),
                         xytext=(0, 9), textcoords="offset points", ha="center", fontsize=8,
                         bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.85))
        eje.set_xlabel("Umbral de confianza de Google")
        eje.set_xticks(g["umbral"])
        eje.set_title(titulo)
        if fmt:
            eje.yaxis.set_major_formatter(fmt)
        eje.set_ylim(0, max(g[col].max(), m[col]) * 1.25)
    ejes[0].legend(frameon=False, loc="lower left", fontsize=8)
    fig.tight_layout()
    return guardar(fig, "res_sensibilidad_umbral")


def main() -> None:
    for f in (figura_dispersion(), figura_sensibilidad()):
        print("escrita:", f)


if __name__ == "__main__":
    main()
