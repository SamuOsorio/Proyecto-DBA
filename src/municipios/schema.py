"""t09 (Samuel): crea `municipios` y `fuentes` con validación $jsonSchema.

Debe:
  - Usar src.common.db.get_database() para la conexión.
  - Definir el validador a partir del diccionario de datos (Entrega 1 sec. 5):
    municipios {_id, nombre, cod_dpto, departamento, subregion_pdet, area_km2,
    geometry, calidad, fuente_id} y fuentes {_id, nombre, version, licencia,
    url_descarga, periodo_imagenes, crs_origen, fecha_descarga, n_registros}.
  - Crear las colecciones con `db.create_collection(..., validator=...)` si no existen.
"""
from pymongo.errors import CollectionInvalid

from src.common.db import get_database

VALIDATOR_MUNICIPIOS = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "_id", "nombre", "cod_dpto", "departamento", "subregion_pdet",
            "area_km2", "geometry", "calidad", "fuente_id",
        ],
        "properties": {
            "_id": {"bsonType": "string", "pattern": "^[0-9]{5}$",
                     "description": "Código DANE del municipio (5 dígitos)"},
            "nombre": {"bsonType": "string"},
            "cod_dpto": {"bsonType": "string", "pattern": "^[0-9]{2}$"},
            "departamento": {"bsonType": "string"},
            "subregion_pdet": {
                "bsonType": "object",
                "required": ["id", "nombre"],
                "properties": {
                    "id": {"bsonType": ["int", "long"]},
                    "nombre": {"bsonType": "string"},
                },
            },
            "area_km2": {"bsonType": "double"},
            "geometry": {
                "bsonType": "object",
                "required": ["type", "coordinates"],
                "properties": {
                    "type": {"enum": ["Polygon", "MultiPolygon"]},
                    "coordinates": {"bsonType": "array"},
                },
            },
            "calidad": {
                "bsonType": "object",
                "required": ["valida", "reparada", "n_vertices"],
                "properties": {
                    "valida": {"bsonType": "bool"},
                    "reparada": {"bsonType": "bool"},
                    "n_vertices": {"bsonType": ["int", "long"]},
                },
            },
            "fuente_id": {"bsonType": "string"},
        },
    }
}

# periodo_imagenes y n_registros se aceptan en null: el MGN (límites, no
# imágenes) no tiene periodo de imágenes, y n_registros lo completa carga.py
# después de insertar, no descarga.py al momento de registrar la fuente.
VALIDATOR_FUENTES = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "_id", "nombre", "version", "licencia", "url_descarga",
            "crs_origen", "fecha_descarga",
        ],
        "properties": {
            "_id": {"enum": ["mgn", "google", "microsoft"]},
            "nombre": {"bsonType": "string"},
            "version": {"bsonType": "string"},
            "licencia": {"bsonType": "string"},
            "url_descarga": {"bsonType": "string"},
            "periodo_imagenes": {"bsonType": ["string", "null"]},
            "crs_origen": {"bsonType": ["string", "null"]},
            "fecha_descarga": {"bsonType": "date"},
            "n_registros": {"bsonType": ["int", "long", "null"]},
        },
    }
}


def _crear_si_falta(db, nombre: str, validador: dict) -> None:
    try:
        db.create_collection(nombre, validator=validador, validationLevel="strict")
        print(f"Colección `{nombre}` creada con validación $jsonSchema.")
    except CollectionInvalid:
        print(f"Colección `{nombre}` ya existía; no se modifica el validador.")


def crear_colecciones():
    db = get_database()
    _crear_si_falta(db, "municipios", VALIDATOR_MUNICIPIOS)
    _crear_si_falta(db, "fuentes", VALIDATOR_FUENTES)


if __name__ == "__main__":
    crear_colecciones()
