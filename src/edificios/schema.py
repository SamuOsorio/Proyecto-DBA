"""e09 (Samuel): crea `edificios_google` y `edificios_microsoft` con $jsonSchema.

Las dos colecciones comparten esquema (Entrega 1, sec. 5). Los campos que una
fuente no trae (`confianza`, `area_m2_fuente` en Microsoft) y `cod_mpio` (se
llena en la semana 4) aceptan null. La validación es estricta: MongoDB rechaza
al insertar cualquier documento que no cumpla.
"""
from pymongo.errors import CollectionInvalid

from src.common.config import load_config
from src.common.db import get_database

VALIDATOR_EDIFICIOS = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "_id", "fuente_id", "geometry", "centroide", "area_m2",
            "geom_hash", "lote_id",
        ],
        "properties": {
            "_id": {"bsonType": "objectId"},
            "fuente_id": {"enum": ["google", "microsoft"]},
            "geometry": {
                "bsonType": "object",
                "required": ["type", "coordinates"],
                "properties": {
                    "type": {"enum": ["Polygon"]},
                    "coordinates": {"bsonType": "array"},
                },
            },
            "centroide": {
                "bsonType": "object",
                "required": ["type", "coordinates"],
                "properties": {
                    "type": {"enum": ["Point"]},
                    "coordinates": {
                        "bsonType": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": {"bsonType": "double"},
                    },
                },
            },
            "area_m2": {"bsonType": "double", "minimum": 0},
            "area_m2_fuente": {"bsonType": ["double", "null"]},
            "confianza": {"bsonType": ["double", "null"], "minimum": 0, "maximum": 1},
            "cod_mpio": {"bsonType": ["string", "null"], "pattern": "^[0-9]{5}$"},
            "geom_hash": {"bsonType": "string"},
            "lote_id": {"bsonType": "objectId"},
        },
    }
}


def _crear_si_falta(db, nombre: str) -> None:
    try:
        db.create_collection(nombre, validator=VALIDATOR_EDIFICIOS, validationLevel="strict")
        print(f"Colección `{nombre}` creada con validación $jsonSchema.")
    except CollectionInvalid:
        print(f"Colección `{nombre}` ya existía; no se modifica el validador.")


def crear_colecciones():
    cfg = load_config()
    db = get_database()
    for clave in ("edificios_google", "edificios_microsoft"):
        _crear_si_falta(db, cfg["database"]["collections"][clave])


if __name__ == "__main__":
    crear_colecciones()
