"""Estimación de potencia instalable y energía en techos (informe final).

Convierte el área conservadora de techos de cada municipio, min(A_G, A_M),
en potencia pico y energía anual con supuestos explícitos que se leen de
config.yaml (sección `potencial`):

  P [kWp]      = A [m2] * aprovechamiento * densidad_kwp_m2
  E [kWh/año]  = P * irradiacion_kwh_m2_dia * 365 * rendimiento_global

Es un orden de magnitud: usa una sola irradiación para todo el país y un
factor de aprovechamiento fijo. Para un escenario bajo y uno alto se usan
los extremos de `aprovechamiento_rango`.

Lee data/processed/ranking_municipios.csv (lo escribe `ranking.py`), así que
no necesita la base.

Salidas:
  data/processed/potencial_municipios.csv   los 170 municipios
  Informe Final/tablas/potencial.tex        top 15 y total PDET

Uso:
  python -m src.analisis.potencial
"""
from __future__ import annotations

import pandas as pd

from src.analisis.exportar import miles, num_es
from src.common.config import ROOT, load_config

TOP = 15


def parametros(cfg: dict) -> dict:
    p = cfg["potencial"]
    return {
        "aprov": float(p["aprovechamiento"]),
        "aprov_bajo": float(p["aprovechamiento_rango"][0]),
        "aprov_alto": float(p["aprovechamiento_rango"][1]),
        "kwp_m2": float(p["densidad_kwp_m2"]),
        "hsp": float(p["irradiacion_kwh_m2_dia"]),
        "pr": float(p["rendimiento_global"]),
    }


def calcular(cfg: dict | None = None) -> pd.DataFrame:
    cfg = cfg or load_config()
    p = parametros(cfg)
    df = pd.read_csv(ROOT / "data/processed/ranking_municipios.csv",
                     dtype={"cod_mpio": str})
    area_m2 = df.ha_conservadora * 10_000
    kwh_por_kwp = p["hsp"] * 365 * p["pr"]
    df["mwp"] = area_m2 * p["aprov"] * p["kwp_m2"] / 1_000
    df["mwp_bajo"] = area_m2 * p["aprov_bajo"] * p["kwp_m2"] / 1_000
    df["mwp_alto"] = area_m2 * p["aprov_alto"] * p["kwp_m2"] / 1_000
    df["gwh_ano"] = df.mwp * kwh_por_kwp / 1_000
    return df[["puesto", "cod_mpio", "municipio", "departamento", "subregion",
               "ha_conservadora", "mwp_bajo", "mwp", "mwp_alto", "gwh_ano"]]


def tex(df: pd.DataFrame, cfg: dict) -> str:
    p = parametros(cfg)
    filas = [" & ".join([str(r.puesto), r.municipio, num_es(r.ha_conservadora, 0),
                         miles(r.mwp_bajo), miles(r.mwp), miles(r.mwp_alto),
                         miles(r.gwh_ano)]) + r" \\"
             for r in df.head(TOP).itertuples()]
    top, tot = df.head(TOP), df
    resumen = [
        " & ".join([r"\multicolumn{2}{@{}l}{Top 15}", num_es(top.ha_conservadora.sum(), 0),
                    miles(top.mwp_bajo.sum()), miles(top.mwp.sum()), miles(top.mwp_alto.sum()),
                    miles(top.gwh_ano.sum())]) + r" \\",
        " & ".join([r"\multicolumn{2}{@{}l}{170 municipios PDET}", num_es(tot.ha_conservadora.sum(), 0),
                    miles(tot.mwp_bajo.sum()), miles(tot.mwp.sum()), miles(tot.mwp_alto.sum()),
                    miles(tot.gwh_ano.sum())]) + r" \\",
    ]
    pct = lambda x: num_es(100 * x, 0)
    return "\n".join([
        r"% Generado por src/analisis/potencial.py; no editar a mano.",
        r"\begin{table}[H]",
        r"\centering\small",
        r"\caption{Potencia instalable y energía anual estimadas sobre el área conservadora "
        rf"(orden de magnitud). Aprovechamiento del techo {pct(p['aprov'])}\,\% "
        rf"(rango {pct(p['aprov_bajo'])}--{pct(p['aprov_alto'])}\,\%), "
        rf"{num_es(p['kwp_m2'], 2)}\,kWp/m\textsuperscript{{2}} de módulo, "
        rf"{num_es(p['hsp'], 1)}\,kWh/m\textsuperscript{{2}}/día y rendimiento global {num_es(p['pr'], 2)}.}}",
        r"\label{tab:potencial}",
        r"\begin{tabularx}{\textwidth}{@{}rLrrrrr@{}}",
        r"\toprule",
        r" & & \textbf{Área} & \multicolumn{3}{c}{\textbf{Potencia (MWp)}} & \textbf{Energía} \\",
        r"\cmidrule(lr){4-6}",
        r"\textbf{\#} & \textbf{Municipio} & \textbf{(ha)} & \textbf{Baja} & \textbf{Central} & \textbf{Alta} & \textbf{(GWh/año)} \\",
        r"\midrule",
        *filas,
        r"\midrule",
        *resumen,
        r"\bottomrule",
        r"\end{tabularx}",
        r"\end{table}",
        "",
    ])


def main() -> None:
    cfg = load_config()
    df = calcular(cfg)
    salida_csv = ROOT / "data/processed/potencial_municipios.csv"
    df.to_csv(salida_csv, index=False)
    salida_tex = ROOT / cfg["potencial"]["salida_tex"]
    salida_tex.parent.mkdir(parents=True, exist_ok=True)
    salida_tex.write_text(tex(df, cfg), encoding="utf-8")
    top = df.head(TOP)
    print(f"[potencial] top 15: {top.mwp.sum():,.0f} MWp, {top.gwh_ano.sum():,.0f} GWh/año")
    print(f"[potencial] 170 municipios: {df.mwp.sum():,.0f} MWp "
          f"({df.mwp_bajo.sum():,.0f}-{df.mwp_alto.sum():,.0f}), {df.gwh_ano.sum():,.0f} GWh/año")
    print(f"[potencial] escrito {salida_csv.relative_to(ROOT)} y {salida_tex.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
