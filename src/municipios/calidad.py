"""t07 (Jose Eduardo): chequeo de tamaño BSON por municipio antes de cargar.

Debe:
  - Medir el tamaño BSON de cada documento (bson.BSON.encode) a partir del
    GeoJSON que produce exportar.py (depende de t06, Maria Camila).
  - Señalar cualquier documento que se acerque o pase el límite de 16 MB de
    MongoDB (config.yaml -> municipios.max_bson_bytes) y documentar la tolerancia.
"""
import json

import bson

from src.municipios.geometria import cargar_config, ruta

# Un documento a partir de este porcentaje del límite se reporta como alerta.
# Por debajo no hay riesgo de pasar el límite con los campos que se cargan.
TOLERANCIA = 0.9


def _documento(feature: dict) -> dict:
    """Arma el documento tal como lo guarda carga.py: properties + geometry."""
    return {"_id": feature["id"], **feature["properties"], "geometry": feature["geometry"]}


def chequear_tamanos() -> list[dict]:
    cfg = cargar_config()
    limite = cfg["municipios"]["max_bson_bytes"]
    with open(ruta(cfg, "salida_geojson"), encoding="utf-8") as f:
        features = json.load(f)["features"]

    reporte = []
    for feature in features:
        tam = len(bson.encode(_documento(feature)))
        reporte.append({"_id": feature["id"], "bytes": tam, "porcentaje": tam / limite})

    mayor = max(reporte, key=lambda r: r["bytes"])
    alertas = [r for r in reporte if r["porcentaje"] >= TOLERANCIA]
    excedidos = [r for r in reporte if r["bytes"] > limite]

    print(
        f"[calidad] {len(reporte)} documentos; el mayor es {mayor['_id']} con "
        f"{mayor['bytes']} bytes ({mayor['porcentaje']:.1%} del límite de {limite})."
    )
    for r in alertas:
        print(f"[calidad] ALERTA {r['_id']}: {r['porcentaje']:.1%} del límite")
    if excedidos:
        ids = [r["_id"] for r in excedidos]
        raise ValueError(f"Documentos por encima del límite BSON: {ids}")
    return reporte


if __name__ == "__main__":
    chequear_tamanos()
