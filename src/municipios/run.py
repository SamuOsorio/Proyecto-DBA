"""Entrega 2: orquesta el flujo completo de `municipios` (make municipios).

Cada paso vive en su propio archivo para que el equipo trabaje en paralelo
sin pisarse: descarga.py/cruce.py/verificacion.py (Jorge), geometria.py/
exportar.py (Maria Camila), schema.py/carga.py/indices.py/evidencia.py
(Samuel), mapa.py/calidad.py (Jose Eduardo).
"""
from src.municipios import (
    calidad,
    carga,
    cruce,
    descarga,
    evidencia,
    exportar,
    geometria,
    indices,
    mapa,
    schema,
    verificacion,
)


def main() -> None:
    schema.crear_colecciones()
    descarga.descargar_mgn()
    cruce.cruzar_con_pdet()
    verificacion.verificar_cobertura()
    geometria.validar_y_reparar()
    geometria.reproyectar_y_calcular_area()
    exportar.exportar_geojson()
    calidad.chequear_tamanos()
    mapa.generar_mapa_control()
    carga.cargar_municipios()
    indices.crear_indices()
    evidencia.mostrar_explain()


if __name__ == "__main__":
    main()
