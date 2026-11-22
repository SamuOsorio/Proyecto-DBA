"""Exporta `resultados` a CSV y a tablas LaTeX (semana 4, Samuel).

Salidas:
  data/processed/resultados_municipio.csv  una fila por municipio, fuente y umbral
  data/processed/resultados_subregion.csv  una fila por subregión y fuente (escenario base)
  Entrega 4/tabla_subregion.tex            tabla por subregión, Google vs. Microsoft

El escenario base es Google con el umbral por defecto (0,65) y Microsoft (sin
umbral). Los dos CSV se versionan, igual que municipios_pdet.geojson, para que
los mapas y el ranking se puedan rehacer sin la base. Las agregaciones por
subregión las hace MongoDB ($lookup + $group), no pandas.

Uso:
  python -m src.analisis.exportar
"""
from __future__ import annotations

import re

import pandas as pd

from src.common.config import ROOT, load_config
from src.common.db import get_database

MINUSCULAS = {"de", "del", "y", "la", "las", "el", "los", "en"}


# ------------------------------------------------------------- formato
def tipo_titulo(texto: str) -> str:
    """'ALTO PATÍA Y NORTE DEL CAUCA' -> 'Alto Patía y Norte del Cauca'."""
    palabras = re.split(r"(\s+|-)", texto.strip().lower())
    out = []
    for i, p in enumerate(palabras):
        out.append(p if (i > 0 and p in MINUSCULAS) or not p.strip() or p == "-"
                   else p[:1].upper() + p[1:])
    return re.sub(r"\s*-\s*", " - ", "".join(out))


def miles(x) -> str:
    """Entero con espacio fino de miles para LaTeX: 2694786 -> 2\\,694\\,786."""
    return f"{int(round(x)):,}".replace(",", "\\,")


def num_es(x, nd: int = 1) -> str:
    """Decimal con coma y espacio fino de miles: 1234.56 -> 1\\,234,6."""
    s = f"{x:,.{nd}f}"  # 1,234.5
    return s.replace(",", "X").replace(".", ",").replace("X", "\\,")


def escenario_base(cfg: dict) -> dict:
    """Filtro de `resultados` para el escenario base: Google 0,65 y Microsoft."""
    base = float(cfg["edificios"]["umbral_confianza_google_default"])
    return {"$or": [{"_id.fuente_id": "google", "_id.umbral": base},
                    {"_id.fuente_id": "microsoft", "_id.umbral": None}]}


# ------------------------------------------------------------- consultas
def por_municipio(cfg: dict) -> pd.DataFrame:
    db = get_database()
    col = cfg["database"]["collections"]
    filas = list(db[col["resultados"]].aggregate([
        {"$lookup": {"from": col["municipios"], "localField": "_id.cod_mpio",
                     "foreignField": "_id", "as": "m"}},
        {"$unwind": "$m"},
        {"$project": {
            "_id": 0,
            "cod_mpio": "$_id.cod_mpio",
            "municipio": "$m.nombre",
            "departamento": "$m.departamento",
            "subregion_id": "$m.subregion_pdet.id",
            "subregion": "$m.subregion_pdet.nombre",
            "area_mpio_km2": "$m.area_km2",
            "fuente": "$_id.fuente_id",
            "umbral": "$_id.umbral",
            "n_edificios": 1, "area_total_m2": 1, "area_media_m2": 1,
            "densidad_km2": 1, "pct_techos": 1,
        }},
        {"$sort": {"cod_mpio": 1, "fuente": 1, "umbral": 1}},
    ]))
    return pd.DataFrame(filas)


def por_subregion(cfg: dict) -> pd.DataFrame:
    db = get_database()
    col = cfg["database"]["collections"]
    filas = list(db[col["resultados"]].aggregate([
        {"$match": escenario_base(cfg)},
        {"$lookup": {"from": col["municipios"], "localField": "_id.cod_mpio",
                     "foreignField": "_id", "as": "m"}},
        {"$unwind": "$m"},
        {"$group": {
            "_id": {"subregion_id": "$m.subregion_pdet.id",
                    "subregion": "$m.subregion_pdet.nombre",
                    "fuente": "$_id.fuente_id"},
            "municipios": {"$sum": 1},
            "municipios_sin_edificios": {"$sum": {"$cond": [{"$eq": ["$n_edificios", 0]}, 1, 0]}},
            "n_edificios": {"$sum": "$n_edificios"},
            "area_total_m2": {"$sum": "$area_total_m2"},
            "area_subregion_km2": {"$sum": "$m.area_km2"},
        }},
        {"$project": {
            "_id": 0,
            "subregion_id": "$_id.subregion_id", "subregion": "$_id.subregion",
            "fuente": "$_id.fuente", "municipios": 1, "municipios_sin_edificios": 1,
            "n_edificios": 1,
            "area_total_km2": {"$divide": ["$area_total_m2", 1e6]},
            "area_subregion_km2": 1,
            "densidad_km2": {"$divide": ["$n_edificios", "$area_subregion_km2"]},
            "pct_techos": {"$multiply": [100, {"$divide": [
                "$area_total_m2", {"$multiply": ["$area_subregion_km2", 1e6]}]}]},
        }},
        {"$sort": {"subregion_id": 1, "fuente": 1}},
    ]))
    df = pd.DataFrame(filas)
    df["subregion"] = df["subregion"].map(tipo_titulo)
    return df


# ------------------------------------------------------------- LaTeX
def tex_subregion(df: pd.DataFrame) -> str:
    """Tabla ancha: una fila por subregión con Google y Microsoft lado a lado."""
    w = df.pivot_table(index=["subregion_id", "subregion", "municipios"], columns="fuente",
                       values=["n_edificios", "area_total_km2"], aggfunc="sum").reset_index()
    w.columns = ["_".join(c).strip("_") for c in w.columns]
    w["D"] = ((w.area_total_km2_google - w.area_total_km2_microsoft)
              / (w.area_total_km2_google + w.area_total_km2_microsoft))
    w = w.sort_values("area_total_km2_google", ascending=False)

    def con_signo(d: float) -> str:
        d = round(d, 2)
        return ("$+$" if d > 0 else "$-$" if d < 0 else "") + num_es(abs(d), 2)

    def fila(nombre, mpios, ng, nm, ag, am, d, negrita=False):
        celdas = [nombre, str(int(mpios)), miles(ng), miles(nm), num_es(ag, 2), num_es(am, 2),
                  con_signo(d)]
        if negrita:
            celdas = [f"\\textbf{{{c}}}" for c in celdas]
        return " & ".join(celdas) + " \\\\"

    cuerpo = "\n".join(fila(r.subregion, r.municipios, r.n_edificios_google,
                            r.n_edificios_microsoft, r.area_total_km2_google,
                            r.area_total_km2_microsoft, r.D) for r in w.itertuples())
    ag, am = w.area_total_km2_google.sum(), w.area_total_km2_microsoft.sum()
    total = fila("Total", w.municipios.sum(), w.n_edificios_google.sum(),
                 w.n_edificios_microsoft.sum(), ag, am, (ag - am) / (ag + am), negrita=True)
    return (
        "\\begin{table}[H]\n\\centering\\small\n"
        "\\caption{Edificios y área de techos por subregión PDET (Google con umbral 0,65). "
        "$D = (A_G - A_M)/(A_G + A_M)$; positivo si Google tiene más área.}\n"
        "\\label{tab:subregion}\n"
        "\\begin{tabularx}{\\textwidth}{@{}>{\\raggedright\\arraybackslash}Xrrrrrr@{}}\n\\toprule\n"
        " & & \\multicolumn{2}{c}{\\textbf{Edificios}} & "
        "\\multicolumn{2}{c}{\\textbf{Área de techos (km\\textsuperscript{2})}} & \\\\\n"
        "\\cmidrule(lr){3-4}\\cmidrule(lr){5-6}\n"
        "\\textbf{Subregión} & \\textbf{Mpios.} & \\textbf{Google} & \\textbf{Microsoft} & "
        "\\textbf{Google} & \\textbf{Microsoft} & $\\boldsymbol{D}$ \\\\\n\\midrule\n"
        f"{cuerpo}\n\\midrule\n{total}\n\\bottomrule\n\\end{{tabularx}}\n\\end{{table}}\n")


# ------------------------------------------------------------- principal
def exportar() -> dict:
    cfg = load_config()
    salidas = cfg["analisis"]["salida_csv"]
    informe = ROOT / cfg["analisis"]["carpeta_informe"]
    informe.mkdir(parents=True, exist_ok=True)

    mun = por_municipio(cfg)
    if mun.empty:
        raise RuntimeError("`resultados` está vacía. Corre antes `python -m src.analisis.agregacion`.")
    sub = por_subregion(cfg)

    ruta_mun, ruta_sub = ROOT / salidas["municipio"], ROOT / salidas["subregion"]
    ruta_mun.parent.mkdir(parents=True, exist_ok=True)
    mun.to_csv(ruta_mun, index=False, encoding="utf-8-sig")
    sub.to_csv(ruta_sub, index=False, encoding="utf-8-sig")
    (informe / "tabla_subregion.tex").write_text(tex_subregion(sub), encoding="utf-8")

    print(f"[exportar] {len(mun):,} filas -> {ruta_mun.relative_to(ROOT)}")
    print(f"[exportar] {len(sub):,} filas -> {ruta_sub.relative_to(ROOT)}")
    print(f"[exportar] tabla por subregión -> {(informe / 'tabla_subregion.tex').relative_to(ROOT)}")
    return {"municipio": ruta_mun, "subregion": ruta_sub}


if __name__ == "__main__":
    exportar()
