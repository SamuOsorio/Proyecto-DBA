"""Evidencia de que $geoWithin sobre `centroide` usa el índice 2dsphere (semana 4).

Para cada fuente corre `explain("executionStats")` de la misma consulta $geoWithin
(la ventana es el polígono de un municipio) dos veces:
  - con el planificador libre: debe elegir IXSCAN sobre `centroide_2dsphere`;
  - con hint({$natural: 1}): fuerza COLLSCAN, el recorrido completo.
Compara documentos examinados y tiempos. La salida de consola es la que se captura
como cap_explain_geowithin.png.

Salidas en data/processed/: evidencia_geowithin.csv, evidencia_geowithin.tex y
explain_geowithin_<fuente>.json (los dos explain completos).

Uso:
  python -m src.analisis.evidencia                    # las dos fuentes, municipio 19137
  python -m src.analisis.evidencia google --municipio 27001
"""
from __future__ import annotations

import argparse
import csv
import json

from src.common.config import ROOT, load_config
from src.common.db import get_database

FUENTES = ("google", "microsoft")
MUNICIPIO_PRUEBA = "19137"  # Caldono: el mismo de la evidencia de la semana 3
PROCESADOS = ROOT / "data" / "processed"


def _plan(winning: dict) -> dict:
    return winning.get("queryPlan", winning)  # MongoDB 8 puede envolver el plan en queryPlan


def _etapas(plan: dict) -> list[str]:
    plan = _plan(plan)
    nombres = [plan["stage"]]
    for hijo in [plan.get("inputStage"), *(plan.get("inputStages") or [])]:
        if isinstance(hijo, dict):
            nombres.extend(_etapas(hijo))
    return nombres


def _indice(plan: dict):
    plan = _plan(plan)
    if plan.get("stage") == "IXSCAN":
        return plan.get("indexName")
    for hijo in [plan.get("inputStage"), *(plan.get("inputStages") or [])]:
        if isinstance(hijo, dict) and (n := _indice(hijo)):
            return n
    return None


def _explain(db, coleccion, filtro: dict, hint=None) -> tuple[dict, dict]:
    orden = {"find": coleccion.name, "filter": filtro}
    if hint:
        orden["hint"] = hint
    crudo = db.command({"explain": orden, "verbosity": "executionStats"})
    ganador = crudo["queryPlanner"]["winningPlan"]
    est = crudo["executionStats"]
    resumen = {
        "etapas": _etapas(ganador), "indice": _indice(ganador),
        "devueltos": est["nReturned"], "claves_examinadas": est["totalKeysExamined"],
        "docs_examinados": est["totalDocsExamined"], "ms": est["executionTimeMillis"],
    }
    return resumen, crudo


def evidenciar(fuente: str, cod_mpio: str = MUNICIPIO_PRUEBA) -> list[dict]:
    cfg = load_config()
    db = get_database()
    c = cfg["database"]["collections"]
    col = db[c[f"edificios_{fuente}"]]
    mun = db[c["municipios"]].find_one({"_id": cod_mpio}, {"nombre": 1, "geometry": 1})
    if mun is None:
        mun = next(iter(db[c["municipios"]].find({}, {"nombre": 1, "geometry": 1}).sort("_id", 1)), None)
        if mun is None:
            raise RuntimeError("La colección `municipios` está vacía.")
        print(f"[evidencia] AVISO: no existe el municipio {cod_mpio}; se usa {mun['nombre']} ({mun['_id']}).")
        cod_mpio = mun["_id"]
    filtro = {"centroide": {"$geoWithin": {"$geometry": mun["geometry"]}}}

    _explain(db, col, filtro)  # calentamiento: carga el índice en memoria
    con_indice, crudo_ix = _explain(db, col, filtro)
    sin_indice, crudo_cs = _explain(db, col, filtro, hint={"$natural": 1})

    if "IXSCAN" not in con_indice["etapas"] or "COLLSCAN" in con_indice["etapas"]:
        raise AssertionError(f"{fuente}: el planificador no usó el índice ({con_indice['etapas']})")
    if "COLLSCAN" not in sin_indice["etapas"]:
        raise AssertionError(f"{fuente}: hint $natural no dio COLLSCAN ({sin_indice['etapas']})")

    PROCESADOS.mkdir(parents=True, exist_ok=True)
    (PROCESADOS / f"explain_geowithin_{fuente}.json").write_text(
        json.dumps({"con_indice": crudo_ix, "collscan": crudo_cs}, indent=2, default=str),
        encoding="utf-8")

    filas = []
    for nombre, r in (("IXSCAN", con_indice), ("COLLSCAN", sin_indice)):
        filas.append({"fuente": fuente, "municipio": f"{mun['nombre']} ({cod_mpio})", "plan": nombre,
                      "indice": r["indice"] or "-", "devueltos": r["devueltos"],
                      "claves_examinadas": r["claves_examinadas"],
                      "docs_examinados": r["docs_examinados"], "ms": r["ms"]})
    ix, cs = filas
    mejora_t = cs["ms"] / ix["ms"] if ix["ms"] else float("inf")
    mejora_d = cs["docs_examinados"] / max(ix["docs_examinados"], 1)

    print(f"\n[evidencia] {fuente} · $geoWithin sobre `centroide` · {mun['nombre']} ({cod_mpio})")
    print(f"  {'plan':9} {'índice':20} {'devueltos':>10} {'claves':>10} {'docs examinados':>16} {'ms':>8}")
    for f in filas:
        print(f"  {f['plan']:9} {f['indice']:20} {f['devueltos']:>10,} {f['claves_examinadas']:>10,} "
              f"{f['docs_examinados']:>16,} {f['ms']:>8,}")
    print(f"  Con el índice se examinan {mejora_d:,.1f}x menos documentos y la consulta es "
          f"{mejora_t:,.1f}x más rápida.")
    return filas


def _tex(filas: list[dict]) -> str:
    def n(x): return f"{int(x):,}".replace(",", "\\,")
    cuerpo = "\n".join(
        f"{f['fuente'].capitalize()} & {f['plan']} & {n(f['devueltos'])} & {n(f['claves_examinadas'])} "
        f"& {n(f['docs_examinados'])} & {n(f['ms'])} \\\\" for f in filas)
    return ("\\begin{table}[H]\n\\centering\\small\n"
            "\\caption{\\texttt{explain(\"executionStats\")} de \\texttt{\\$geoWithin} sobre "
            "\\texttt{centroide}: con el índice y forzando \\texttt{COLLSCAN}.}\n\\label{tab:explain-geowithin}\n"
            "\\begin{tabular}{@{}llrrrr@{}}\n\\toprule\n"
            "\\textbf{Fuente} & \\textbf{Plan} & \\textbf{Devueltos} & \\textbf{Claves} & "
            "\\textbf{Docs examinados} & \\textbf{ms} \\\\\n\\midrule\n"
            f"{cuerpo}\n\\bottomrule\n\\end{{tabular}}\n\\end{{table}}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="explain de $geoWithin: IXSCAN vs COLLSCAN")
    ap.add_argument("fuentes", nargs="*", help="google y/o microsoft (por defecto, las dos)")
    ap.add_argument("--municipio", default=MUNICIPIO_PRUEBA, help="código DANE de la ventana de prueba")
    a = ap.parse_args()
    malas = [f for f in a.fuentes if f not in FUENTES]
    if malas:
        ap.error(f"fuente desconocida: {malas}; usa {list(FUENTES)}")
    todas = []
    for f in (a.fuentes or FUENTES):
        todas += evidenciar(f, a.municipio)
    salida = PROCESADOS / "evidencia_geowithin.csv"
    with open(salida, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(todas[0]))
        w.writeheader()
        w.writerows(todas)
    (PROCESADOS / "evidencia_geowithin.tex").write_text(_tex(todas), encoding="utf-8")
    print(f"\n[evidencia] guardado en {salida} y evidencia_geowithin.tex")
