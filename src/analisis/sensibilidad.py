"""Sensibilidad al umbral de confianza de Google (semana 4, Samuel).

Lee `resultados` (ya calculado por agregacion.py para cada umbral de
config.yaml) y arma la tabla: edificios, área total, % que se pierde frente al
umbral base, municipios con edificios y cuántos del top 15 por área se
mantienen. Microsoft entra como referencia (no tiene confianza).

Salidas: Entrega 4/sensibilidad.csv y Entrega 4/sensibilidad.tex

Uso:
  python -m src.analisis.sensibilidad
"""
from __future__ import annotations

import pandas as pd

from src.analisis.exportar import miles, num_es
from src.common.config import ROOT, load_config
from src.common.db import get_database

TOP = 15


def totales(cfg: dict) -> pd.DataFrame:
    """Un renglón por fuente y umbral, sumado en MongoDB."""
    db = get_database()
    filas = list(db[cfg["database"]["collections"]["resultados"]].aggregate([
        {"$group": {
            "_id": {"fuente": "$_id.fuente_id", "umbral": "$_id.umbral"},
            "n_edificios": {"$sum": "$n_edificios"},
            "area_total_m2": {"$sum": "$area_total_m2"},
            "municipios_con_edificios": {"$sum": {"$cond": [{"$gt": ["$n_edificios", 0]}, 1, 0]}},
        }},
        {"$project": {"_id": 0, "fuente": "$_id.fuente", "umbral": "$_id.umbral",
                      "n_edificios": 1, "area_total_km2": {"$divide": ["$area_total_m2", 1e6]},
                      "municipios_con_edificios": 1}},
        {"$sort": {"fuente": 1, "umbral": 1}},
    ]))
    return pd.DataFrame(filas)


def top_municipios(cfg: dict, fuente: str, umbral, n: int = TOP) -> list[str]:
    db = get_database()
    cur = (db[cfg["database"]["collections"]["resultados"]]
           .find({"_id.fuente_id": fuente, "_id.umbral": umbral}, {"_id.cod_mpio": 1})
           .sort("area_total_m2", -1).limit(n))
    return [d["_id"]["cod_mpio"] for d in cur]


def tabla(cfg: dict) -> pd.DataFrame:
    t = totales(cfg)
    g = t[t.fuente == "google"].sort_values("umbral").reset_index(drop=True)
    if g.empty:
        raise RuntimeError("No hay resultados de Google. Corre antes `python -m src.analisis.agregacion`.")
    base = g.iloc[0]
    top_base = set(top_municipios(cfg, "google", float(base.umbral)))
    g["pct_perdida_edificios"] = 100 * (1 - g.n_edificios / base.n_edificios)
    g["pct_perdida_area"] = 100 * (1 - g.area_total_km2 / base.area_total_km2)
    g["top15_se_mantienen"] = [len(top_base & set(top_municipios(cfg, "google", float(u))))
                               for u in g.umbral]
    m = t[t.fuente == "microsoft"].copy()
    if not m.empty:
        m["top15_se_mantienen"] = len(top_base & set(top_municipios(cfg, "microsoft", None)))
    return pd.concat([g, m], ignore_index=True)


def tex(df: pd.DataFrame) -> str:
    filas = []
    for r in df.itertuples():
        if r.fuente == "google":
            nombre = f"Google, conf.\\ $\\geq$ {num_es(r.umbral, 2)}"
            perd_n = "--" if r.Index == 0 else num_es(r.pct_perdida_edificios, 1) + "\\,\\%"
            perd_a = "--" if r.Index == 0 else num_es(r.pct_perdida_area, 1) + "\\,\\%"
        else:
            nombre, perd_n, perd_a = "Microsoft (referencia)", "", ""
        filas.append(" & ".join([
            nombre, miles(r.n_edificios), perd_n, num_es(r.area_total_km2, 2), perd_a,
            str(int(r.municipios_con_edificios)), f"{int(r.top15_se_mantienen)}/{TOP}",
        ]) + " \\\\")
        if r.fuente == "google" and r.Index == (df.fuente == "google").sum() - 1:
            filas.append("\\midrule")
    return (
        "\\begin{table}[H]\n\\centering\\small\n"
        "\\caption{Sensibilidad al umbral de confianza de Google. Las pérdidas son frente "
        "a 0,65. \\emph{Mpios.}: municipios con al menos un edificio. \\emph{Top 15}: "
        "cuántos de los 15 municipios con más área de techos con 0,65 siguen en el "
        "top 15.}\n\\label{tab:sensibilidad}\n"
        "\\begin{tabular}{@{}lrrrrrr@{}}\n\\toprule\n"
        " & \\multicolumn{2}{c}{\\textbf{Edificios}} & "
        "\\multicolumn{2}{c}{\\textbf{Área (km\\textsuperscript{2})}} & & \\\\\n"
        "\\cmidrule(lr){2-3}\\cmidrule(lr){4-5}\n"
        "\\textbf{Escenario} & \\textbf{Total} & \\textbf{Pérdida} & "
        "\\textbf{Total} & \\textbf{Pérdida} & \\textbf{Mpios.} & \\textbf{Top 15} \\\\\n\\midrule\n"
        + "\n".join(filas) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")


def sensibilidad() -> pd.DataFrame:
    cfg = load_config()
    df = tabla(cfg)
    carpeta = ROOT / cfg["analisis"]["carpeta_informe"]
    carpeta.mkdir(parents=True, exist_ok=True)
    df.to_csv(carpeta / "sensibilidad.csv", index=False, encoding="utf-8-sig")
    (carpeta / "sensibilidad.tex").write_text(tex(df), encoding="utf-8")
    print("\n=== SENSIBILIDAD AL UMBRAL DE CONFIANZA ===")
    print(df.round(2).to_string(index=False))
    print(f"\nGuardado en {carpeta.relative_to(ROOT)}/sensibilidad.csv y .tex")
    return df


if __name__ == "__main__":
    sensibilidad()
