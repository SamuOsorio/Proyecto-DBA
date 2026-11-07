"""t09 (Samuel): crea `municipios` y `fuentes` con validación $jsonSchema.

Debe:
  - Usar src.common.db.get_database() para la conexión.
  - Definir el validador a partir del diccionario de datos (Entrega 1 sec. 5):
    municipios {_id, nombre, cod_dpto, departamento, subregion_pdet, area_km2,
    geometry, calidad, fuente_id} y fuentes {_id, nombre, version, licencia,
    url_descarga, periodo_imagenes, crs_origen, fecha_descarga, n_registros}.
  - Crear las colecciones con `db.create_collection(..., validator=...)` si no existen.
"""


def crear_colecciones():
    raise NotImplementedError


if __name__ == "__main__":
    crear_colecciones()
