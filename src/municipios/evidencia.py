"""t12 (Samuel): evidencia de que el índice 2dsphere se está usando.

Debe:
  - Correr .explain() sobre una consulta espacial y confirmar la etapa IXSCAN
    (no COLLSCAN).
  - Correr una consulta $geoIntersects con un punto conocido (p.ej. la cabecera
    municipal de algún PDET) y verificar que devuelve el municipio correcto.
  - Guardar la salida para anexarla al informe de la Entrega 2.
"""
import json

from shapely.geometry import shape

from src.common.db import get_database
from src.municipios.geometria import cargar_config, ruta


def _punto_de_control(cfg: dict) -> tuple[str, str, list[float]]:
    """Punto interior de un municipio del geojson exportado (representative_point,
    así que cae dentro del polígono aunque sea cóncavo)."""
    with open(ruta(cfg, "salida_geojson"), encoding="utf-8") as f:
        features = json.load(f)["features"]
    feature = features[0]
    punto = shape(feature["geometry"]).representative_point()
    return feature["properties"]["_id"], feature["properties"]["nombre"], [punto.x, punto.y]


def _etapas(stage: dict) -> list[str]:
    """Nombres de todas las etapas del plan, de afuera hacia adentro."""
    nombres = [stage["stage"]]
    for hijo in ("inputStage", *(stage.get("inputStages") or [])):
        sub = stage.get(hijo) if hijo == "inputStage" else hijo
        if isinstance(sub, dict):
            nombres.extend(_etapas(sub))
    return nombres


def mostrar_explain():
    cfg = cargar_config()
    coleccion = get_database()[cfg["database"]["collections"]["municipios"]]
    cod_mpio, nombre, (lon, lat) = _punto_de_control(cfg)

    consulta = {"geometry": {"$geoIntersects": {"$geometry": {"type": "Point", "coordinates": [lon, lat]}}}}

    plan = coleccion.find(consulta).explain()
    etapas = _etapas(plan["queryPlanner"]["winningPlan"])
    print(f"[evidencia] etapas del plan: {etapas} (se espera IXSCAN, no COLLSCAN)")
    if "COLLSCAN" in etapas or "IXSCAN" not in etapas:
        raise AssertionError(f"El plan no usó el índice 2dsphere como se esperaba: {etapas}")

    encontrados = list(coleccion.find(consulta, {"_id": 1, "nombre": 1}))
    print(f"[evidencia] punto de control: {nombre} ({cod_mpio}) en [{lon:.5f}, {lat:.5f}]")
    print(f"[evidencia] $geoIntersects devolvió: {encontrados}")

    if len(encontrados) != 1 or encontrados[0]["_id"] != cod_mpio:
        raise AssertionError(
            f"Se esperaba que el punto cayera solo en {cod_mpio} ({nombre}); "
            f"devolvió {encontrados}"
        )

    print("[evidencia] OK: el índice 2dsphere se usa (IXSCAN) y el geoIntersects "
          "devuelve el municipio correcto.")
    return {"etapas": etapas, "punto_control": cod_mpio, "resultado": encontrados}


if __name__ == "__main__":
    mostrar_explain()
