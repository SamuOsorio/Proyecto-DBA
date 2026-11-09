"""t11 (Samuel): crea los índices de `municipios`.

Debe:
  - Índice 2dsphere sobre `geometry` (consultas espaciales sobre los límites).
  - Índice sobre `subregion_pdet.id` (resúmenes por subregión).
"""
from src.common.db import get_database
from src.municipios.geometria import cargar_config


def crear_indices():
    cfg = cargar_config()
    coleccion = get_database()[cfg["database"]["collections"]["municipios"]]

    nombre_geo = coleccion.create_index([("geometry", "2dsphere")])
    nombre_sub = coleccion.create_index([("subregion_pdet.id", 1)])

    print(f"[indices] creados: {nombre_geo}, {nombre_sub}")
    return [nombre_geo, nombre_sub]


if __name__ == "__main__":
    crear_indices()
