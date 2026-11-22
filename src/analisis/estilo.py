"""Estilo común de las figuras del informe (Entrega 3 y 4).

Un color fijo por fuente en todo el informe, textos en español, miles con
separador y figuras pensadas para el ancho de página (8 pulgadas).
El título lo pone el \\caption del informe, no la figura.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from src.common.config import ROOT

COLOR_GOOGLE = "#2A78D6"
COLOR_MICROSOFT = "#EB6834"
COLORES = {"Google": COLOR_GOOGLE, "Microsoft": COLOR_MICROSOFT}

NOMBRE_COMPLETO = {
    "Google": "Google Open Buildings",
    "Microsoft": "Microsoft Building Footprints",
}

CARPETA_IMG = ROOT / "Entrega 3" / "img"

mpl.rcParams.update({
    "figure.figsize": (8, 4.5),
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "legend.fontsize": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "savefig.dpi": 300,
})

miles = FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", "."))


def guardar(fig, nombre: str, carpeta: Path = CARPETA_IMG) -> Path:
    """Guarda la figura como PNG a 300 dpi en la carpeta de imágenes del informe."""
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{nombre}.png"
    fig.savefig(ruta, bbox_inches="tight")
    plt.close(fig)
    return ruta
