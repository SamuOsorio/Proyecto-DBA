"""Semana 4: encadena todo el análisis (es lo que corre `make analisis`).

Orden (cada paso es un archivo de src/analisis/, uno por tarea):

  asignacion    Jorge          edificios -> municipio por centroide ($geoWithin)
  evidencia     Jorge          explain(): IXSCAN frente a COLLSCAN
  validacion    Jorge          muestra de 10 municipios contra GeoPandas
  agregacion    Samuel         $group + $merge a `resultados` (fuentes y umbrales)
  sensibilidad  Samuel         tabla de sensibilidad al umbral de Google
  exportar      Samuel         CSV y tabla por subregión
  figuras_eda   Jose Eduardo   las 4 figuras del EDA rehechas
  graficas      Jose Eduardo   dispersión y sensibilidad (si el archivo existe)
  mapas         Maria Camila   mapas por fuente, de diferencia y de % de techos
  ranking       Maria Camila   top 15 por área conservadora

Cada paso corre como `python -m src.analisis.<paso>`, igual que a mano, y si
uno falla el flujo se detiene ahí. Al final imprime cuánto tardó cada paso.

Uso:
  python -m src.analisis.run                     # todo
  python -m src.analisis.run --desde agregacion  # retoma desde un paso
  python -m src.analisis.run --solo-figuras      # mapas y ranking, sin la base
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

from src.common.config import ROOT

PASOS = ["asignacion", "evidencia", "validacion", "agregacion", "sensibilidad",
         "exportar", "figuras_eda", "graficas", "mapas", "ranking"]
OPCIONALES = {"graficas"}           # se salta si el archivo todavía no existe
SIN_BASE = ["mapas", "ranking"]     # leen los CSV y el GeoJSON versionados


def correr(pasos: list[str]) -> list[tuple[str, float, str]]:
    resumen = []
    for paso in pasos:
        if paso in OPCIONALES and not (ROOT / "src" / "analisis" / f"{paso}.py").exists():
            print(f"\n[run] {paso}: no existe src/analisis/{paso}.py, se salta.")
            resumen.append((paso, 0.0, "saltado"))
            continue
        print(f"\n{'=' * 70}\n[run] {paso}\n{'=' * 70}", flush=True)
        inicio = time.perf_counter()
        r = subprocess.run([sys.executable, "-m", f"src.analisis.{paso}"], cwd=ROOT)
        seg = time.perf_counter() - inicio
        if r.returncode != 0:
            resumen.append((paso, seg, "FALLÓ"))
            _imprimir(resumen)
            sys.exit(f"[run] {paso} terminó con error (código {r.returncode}). "
                     f"Corrige y retoma con: python -m src.analisis.run --desde {paso}")
        resumen.append((paso, seg, "ok"))
    _imprimir(resumen)
    return resumen


def _imprimir(resumen) -> None:
    print(f"\n{'=' * 70}\n[run] RESUMEN DE LA CORRIDA\n{'=' * 70}")
    for paso, seg, estado in resumen:
        print(f"  {paso:<14} {estado:<8} {seg:8.1f} s")
    print(f"  {'total':<14} {'':<8} {sum(s for _, s, _ in resumen):8.1f} s")


def main() -> None:
    ap = argparse.ArgumentParser(description="Flujo completo de la semana 4")
    ap.add_argument("--desde", choices=PASOS, help="retoma desde este paso")
    ap.add_argument("--solo-figuras", action="store_true",
                    help="solo mapas y ranking (no necesita MongoDB)")
    a = ap.parse_args()
    if a.solo_figuras:
        pasos = SIN_BASE
    elif a.desde:
        pasos = PASOS[PASOS.index(a.desde):]
    else:
        pasos = PASOS
    correr(pasos)


if __name__ == "__main__":
    main()
