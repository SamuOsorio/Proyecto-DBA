"""t08 (Maria Camila): exporta el GeoJSON final listo para cargar.

Lee la capa que deja geometria.py y escribe config.yaml ->
municipios.salida_geojson con el esquema de la colección `municipios`
(Entrega 1, sección 5.1):

  _id            string(5)  código DANE del municipio, con cero inicial
  nombre         string
  cod_dpto       string(2)
  departamento   string
  subregion_pdet {id: int, nombre: string}
  area_km2       double     calculada en EPSG:9377
  geometry       Polygon | MultiPolygon en WGS84 [lon, lat]
  calidad        {valida: bool, reparada: bool, n_vertices: int}
  fuente_id      "mgn"

Cada Feature del GeoJSON lleva esos campos en `properties` (más `id` = _id),
así carga.py solo tiene que juntar properties + geometry en un documento.
Este archivo SÍ se commitea al repo.
"""
from __future__ import annotations

import json
import unicodedata

import geopandas as gpd
from shapely.geometry import mapping

from src.municipios.geometria import cargar_config, ruta

# Nombres posibles de cada columna en la capa que entrega el cruce
# (MGN en minúsculas o mayúsculas, o columnas del Excel PDET).
CANDIDATOS = {
    "cod_mpio": ["cod_mpio", "mpio_cdpmp", "codigo_dane", "cod_dane",
                 "codigo dane municipio"],
    "nombre": ["nombre_pdet", "nombre", "mpio_cnmbr", "nombre_mgn", "municipio"],
    "cod_dpto": ["cod_dpto", "dpto_ccdgo", "codigo dane departamento"],
    "departamento": ["departamento_pdet", "departamento", "dpto_cnmbr"],
    "subregion": ["subregion_pdet", "subregion", "subregion pdet"],
}


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.strip().lower().replace("_", " ")


def _columna(gdf: gpd.GeoDataFrame, campo: str, obligatoria: bool = True):
    disponibles = {_normalizar(c): c for c in gdf.columns}
    for cand in CANDIDATOS[campo]:
        if _normalizar(cand) in disponibles:
            return disponibles[_normalizar(cand)]
    if obligatoria:
        raise KeyError(
            f"No encontré la columna para '{campo}'. Columnas disponibles: "
            f"{list(gdf.columns)}. Agrega el nombre a CANDIDATOS en exportar.py."
        )
    return None


def _codigo(valor, digitos: int) -> str:
    texto = str(valor).strip()
    if texto.endswith(".0"):          # por si llegó como float desde el Excel
        texto = texto[:-2]
    return texto.zfill(digitos)


def exportar_geojson(gdf: gpd.GeoDataFrame | None = None) -> dict:
    cfg = cargar_config()
    if gdf is None:
        gdf = gpd.read_file(ruta(cfg, "intermedio_geometria"))

    c_mpio = _columna(gdf, "cod_mpio")
    c_nombre = _columna(gdf, "nombre")
    c_dpto = _columna(gdf, "cod_dpto", obligatoria=False)
    c_depto = _columna(gdf, "departamento")
    c_sub = _columna(gdf, "subregion")

    # id de subregión: 1..16 en orden alfabético (estable entre ejecuciones).
    subregiones = sorted(gdf[c_sub].astype(str).str.strip().unique())
    id_subregion = {nombre: i for i, nombre in enumerate(subregiones, start=1)}

    features = []
    for _, fila in gdf.iterrows():
        cod_mpio = _codigo(fila[c_mpio], 5)
        sub = str(fila[c_sub]).strip()
        props = {
            "_id": cod_mpio,
            "nombre": str(fila[c_nombre]).strip(),
            "cod_dpto": _codigo(fila[c_dpto], 2) if c_dpto else cod_mpio[:2],
            "departamento": str(fila[c_depto]).strip(),
            "subregion_pdet": {"id": id_subregion[sub], "nombre": sub},
            "area_km2": round(float(fila["area_km2"]), 4),
            "calidad": {
                "valida": bool(fila["calidad_valida"]),
                "reparada": bool(fila["calidad_reparada"]),
                "n_vertices": int(fila["calidad_n_vertices"]),
            },
            "fuente_id": "mgn",
        }
        features.append({
            "type": "Feature",
            "id": cod_mpio,
            "properties": props,
            "geometry": mapping(fila.geometry),
        })

    _validar(features)

    salida = {"type": "FeatureCollection", "features": features}
    destino = ruta(cfg, "salida_geojson")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False)

    mb = destino.stat().st_size / 1e6
    print(f"[exportar] {len(features)} municipios -> {destino} ({mb:.1f} MB)")
    if mb > 90:
        print("[exportar] OJO: GitHub no acepta archivos de más de 100 MB.")
    return salida


def _validar(features: list[dict]) -> None:
    ids = [f["properties"]["_id"] for f in features]
    if len(ids) != len(set(ids)):
        raise ValueError("Hay códigos DANE repetidos.")
    malos = [i for i in ids if len(i) != 5 or not i.isdigit()]
    if malos:
        raise ValueError(f"Códigos DANE con formato incorrecto: {malos[:10]}")
    tipos = {f["geometry"]["type"] for f in features}
    if not tipos <= {"Polygon", "MultiPolygon"}:
        raise ValueError(f"Tipos de geometría no permitidos: {tipos}")
    if len(features) != 170:
        print(f"[exportar] Aviso: se esperaban 170 municipios y hay {len(features)}.")


if __name__ == "__main__":
    exportar_geojson()
