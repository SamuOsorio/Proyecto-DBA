"""Ranking de municipios candidatos (semana 4, Maria Camila).

Criterio: área conservadora = min(A_G, A_M), el área de techos que las DOS
fuentes respaldan. Así un municipio no sube en el ranking solo porque una
fuente lo sobreestima. Se marcan como "fuentes en desacuerdo" los municipios
con |D| > 0,3, donde D = (A_G - A_M) / (A_G + A_M).

Salidas:
  Entrega 4/ranking.tex             tabla del top 15 para el informe
  Entrega 4/img/ranking_top15.png   barras horizontales, Google y Microsoft
  data/processed/ranking_municipios.csv   los 170 municipios ordenados

Lee los mismos archivos versionados que `mapas.py` (no necesita la base).

Uso:
  python -m src.analisis.ranking
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.analisis.estilo import COLOR_GOOGLE, COLOR_MICROSOFT, NOMBRE_COMPLETO, guardar, miles
from src.analisis.exportar import tipo_titulo
from src.analisis.mapas import cargar
from src.common.config import ROOT, load_config

TOP = 15
UMBRAL_DESACUERDO = 0.3


def num_tex(x: float, nd: int = 1) -> str:
    """Decimal con coma y espacio fino de miles para LaTeX."""
    s = f"{x:,.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", "\\,")


def tabla_ranking(cfg: dict | None = None) -> pd.DataFrame:
    gdf = cargar(cfg)
    df = pd.DataFrame(gdf.drop(columns="geometry"))
    df["ha_conservadora"] = df[["ha_google", "ha_microsoft"]].min(axis=1)
    df["desacuerdo"] = df.D.abs() > UMBRAL_DESACUERDO
    df["subregion"] = df.subregion_pdet.map(lambda s: tipo_titulo(s["nombre"]))
    df["municipio"] = df.nombre.map(tipo_titulo)
    df["departamento_t"] = df.departamento.map(tipo_titulo)
    df = df.sort_values("ha_conservadora", ascending=False).reset_index(drop=True)
    df.insert(0, "puesto", np.arange(1, len(df) + 1))
    return df


def tex_ranking(df: pd.DataFrame) -> str:
    filas = []
    for r in df.head(TOP).itertuples():
        marca = "$^{\\dagger}$" if r.desacuerdo else ""
        d = round(r.D, 2)
        signo = "$+$" if d > 0 else "$-$" if d < 0 else ""
        filas.append(" & ".join([
            str(r.puesto), f"{r.municipio}{marca}", r.departamento_t, r.subregion,
            num_tex(r.ha_google, 0), num_tex(r.ha_microsoft, 0),
            f"\\textbf{{{num_tex(r.ha_conservadora, 0)}}}",
            signo + num_tex(abs(d), 2), num_tex(r.pct_techos, 2)]) + " \\\\")
    return (
        "\\begin{table}[H]\n\\centering\\scriptsize\n"
        f"\\caption{{Top {TOP} de municipios candidatos, ordenados por el área conservadora "
        "$\\min(A_G, A_M)$ (escenario base: Google con umbral 0,65). Áreas en hectáreas "
        "(1\\,ha $=$ 10\\,000\\,m\\textsuperscript{2}). $D = (A_G - A_M)/(A_G + A_M)$. "
        "\\% techos: superficie del municipio cubierta por techos, promedio de las dos "
        f"fuentes. $^{{\\dagger}}$Fuentes en desacuerdo ($|D| > {num_tex(UMBRAL_DESACUERDO, 1)}$).}}\n"
        "\\label{tab:ranking}\n"
        "\\setlength{\\tabcolsep}{3.5pt}\n"
        "\\begin{tabularx}{\\textwidth}{@{}r>{\\raggedright\\arraybackslash}p{2.6cm}"
        ">{\\raggedright\\arraybackslash}p{1.7cm}>{\\raggedright\\arraybackslash}X"
        "rrrrr@{}}\n\\toprule\n"
        " & & & & \\multicolumn{3}{c}{\\textbf{Área de techos (ha)}} & & \\\\\n"
        "\\cmidrule(lr){5-7}\n"
        "\\textbf{\\#} & \\textbf{Municipio} & \\textbf{Depto.} & \\textbf{Subregión} & "
        "\\textbf{Google} & \\textbf{Microsoft} & \\textbf{Conserv.} & $\\boldsymbol{D}$ & "
        "\\textbf{\\% techos} \\\\\n\\midrule\n"
        + "\n".join(filas)
        + "\n\\bottomrule\n\\end{tabularx}\n\\end{table}\n")


def figura_ranking(df: pd.DataFrame):
    top = df.head(TOP).iloc[::-1]  # el primero arriba
    y = np.arange(len(top))
    alto = 0.38
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(y + alto / 2, top.ha_google, height=alto, color=COLOR_GOOGLE,
            label=NOMBRE_COMPLETO["Google"], edgecolor="white", linewidth=1)
    ax.barh(y - alto / 2, top.ha_microsoft, height=alto, color=COLOR_MICROSOFT,
            label=NOMBRE_COMPLETO["Microsoft"], edgecolor="white", linewidth=1)
    etiquetas = [f"{r.puesto}. {r.municipio}{' †' if r.desacuerdo else ''}"
                 for r in top.itertuples()]
    ax.set_yticks(y, etiquetas)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_formatter(miles)
    ax.set_xlabel("Área de techos (ha)")
    ax.grid(axis="x", color="#e5e5e5", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", frameon=False)
    if top.desacuerdo.any():
        ax.text(1, -0.12, "† Fuentes en desacuerdo (|D| > 0,3)", transform=ax.transAxes,
                ha="right", va="top", fontsize=8, color="#555555")
    fig.tight_layout()
    return fig


def generar_ranking() -> pd.DataFrame:
    cfg = load_config()
    informe = ROOT / cfg["analisis"]["carpeta_informe"]
    df = tabla_ranking(cfg)

    cols = ["puesto", "cod_mpio", "municipio", "departamento_t", "subregion", "ha_google",
            "ha_microsoft", "ha_conservadora", "D", "desacuerdo", "pct_techos",
            "n_edificios_google", "n_edificios_microsoft"]
    salida = ROOT / "data" / "processed" / "ranking_municipios.csv"
    df[cols].rename(columns={"departamento_t": "departamento"}).to_csv(
        salida, index=False, encoding="utf-8-sig")
    (informe / "ranking.tex").write_text(tex_ranking(df), encoding="utf-8")
    fig = guardar(figura_ranking(df), "ranking_top15", informe / "img")

    top = df.head(TOP)
    print(f"\n=== TOP {TOP} POR ÁREA CONSERVADORA min(A_G, A_M) ===")
    print(top[["puesto", "municipio", "departamento_t", "ha_google", "ha_microsoft",
               "ha_conservadora", "D", "desacuerdo"]].round(2).to_string(index=False))
    print(f"\n[ranking] {int(top.desacuerdo.sum())} del top {TOP} con fuentes en desacuerdo; "
          f"{int(df.desacuerdo.sum())} de 170 en total.")
    print(f"[ranking] escrito {salida.relative_to(ROOT)}, "
          f"{(informe / 'ranking.tex').relative_to(ROOT)} y {fig.relative_to(ROOT)}")
    return df


if __name__ == "__main__":
    generar_ranking()
