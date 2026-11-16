"""`make edificios`: descarga -> limpieza -> esquema -> carga -> índices -> evidencia.

Cada paso es reanudable. Por defecto procesa las dos fuentes; para una sola:
    python -m src.edificios.run microsoft
"""
from __future__ import annotations

import sys

from src.edificios import carga, evidencia, indices, schema


def main(fuentes: list[str]) -> None:
    schema.crear_colecciones()
    for f in fuentes:
        if f == "microsoft":
            from src.edificios import descarga_microsoft, limpieza_microsoft
            descarga_microsoft.descargar_microsoft()
            limpieza_microsoft.limpiar_microsoft()
        elif f == "google":
            from src.edificios import descarga_google, limpieza_google
            descarga_google.descargar_google(solo_pdet=True)
            limpieza_google.main()
        carga.cargar(f)
        indices.crear_indices(f)
        evidencia.evidenciar(f)


if __name__ == "__main__":
    main(sys.argv[1:] or ["google", "microsoft"])
