"""Verifica que cada documento GeoJSON quepa en el límite BSON de MongoDB (16 MB).

Uso:
    python scripts/chequeo_bson.py data/processed/municipios.geojson [otro.geojson ...]

Cada feature se mide como se guardaría en MongoDB: propiedades + geometry
+ _id. Termina con código 1 si algún documento supera el límite.
"""

import json
import sys
from pathlib import Path

import bson

LIMITE_BSON = 16 * 1024 * 1024  # 16 MiB, límite de MongoDB por documento


def tamanos(ruta):
    """Devuelve (id, bytes) por cada feature del archivo GeoJSON."""
    with open(ruta, encoding="utf-8") as f:
        coleccion = json.load(f)
    for i, feature in enumerate(coleccion["features"]):
        doc = {
            "_id": feature.get("id", i),
            **feature.get("properties", {}),
            "geometry": feature["geometry"],
        }
        yield doc["_id"], len(bson.encode(doc))


def main(rutas):
    excedidos = 0
    for ruta in rutas:
        mayor_id, mayor = None, 0
        total = 0
        for doc_id, tam in tamanos(Path(ruta)):
            total += 1
            if tam > mayor:
                mayor_id, mayor = doc_id, tam
            if tam > LIMITE_BSON:
                excedidos += 1
                print(f"EXCEDE {ruta}: _id={doc_id} tiene {tam} bytes")
        print(
            f"{ruta}: {total} documentos, mayor {mayor} bytes "
            f"({mayor / LIMITE_BSON:.1%} del límite) en _id={mayor_id}"
        )
    if excedidos:
        print(f"{excedidos} documento(s) superan 16 MB")
        return 1
    print("Todos los documentos están por debajo de 16 MB")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Indique al menos un archivo GeoJSON")
    sys.exit(main(sys.argv[1:]))
