"""t01 (Jorge): descarga el MGN 2025 del geoportal del DANE.
 
Debe:
  - Bajar la capa municipal a config.yaml -> fuentes.mgn.destino_local.
  - Calcular el checksum SHA-256 del archivo descargado.
  - Registrar en la colección `fuentes` (_id="mgn"): url_descarga, version,
    fecha_descarga, crs_origen (ver diccionario de datos, Entrega 1 sec. 5).
 
El geoportal del DANE genera la descarga desde una página web, así que hay dos
formas de dar el archivo (se prueban en este orden):
  1. Un ZIP ya puesto a mano en la carpeta destino (data/raw/mgn_2025/).
  2. Una URL directa del ZIP: argumento `url_directa`, variable de entorno
     MGN_URL_DIRECTA, o config.yaml -> fuentes.mgn.url_directa (opcional).
 
Uso:  python -m src.municipios.descarga
"""
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
 
import requests
 
from src.common.config import ROOT, load_config, mongo_uri
 
NOMBRE_ZIP = "MGN2025.zip"
 
 
def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()
 
 
def _bajar(url: str, destino: Path) -> None:
    print(f"Descargando {url}")
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with destino.open("wb") as f:
            for bloque in r.iter_content(chunk_size=1024 * 1024):
                f.write(bloque)
 
 
def _descomprimir(zip_path: Path, destino: Path, nivel: int = 0) -> None:
    """Descomprime el ZIP y, si trae ZIPs adentro (uno por capa), también esos."""
    destino.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(destino)
    if nivel >= 3:
        return
    for interno in list(destino.rglob("*.zip")):
        sub = interno.with_suffix("")
        if not sub.exists():
            _descomprimir(interno, sub, nivel + 1)
 
 
def _crs_origen(carpeta: Path):
    """Lee el CRS del .prj de la capa municipal (None si no se encuentra)."""
    try:
        import geopandas as gpd
        from src.municipios.cruce import localizar_capa_municipal
        capa = gpd.read_file(localizar_capa_municipal(carpeta), rows=1)
        return str(capa.crs) if capa.crs else None
    except Exception as e:  # no debe tumbar la descarga
        print(f"AVISO: no pude leer el CRS de la capa ({e})")
        return None
 
 
def _registrar_en_mongo(cfg: dict, doc: dict) -> None:
    try:
        from pymongo import MongoClient
        cliente = MongoClient(mongo_uri(cfg), serverSelectionTimeoutMS=5000)
        col = cliente[cfg["database"]["name"]][cfg["database"]["collections"]["fuentes"]]
        campos = {k: v for k, v in doc.items() if k != "_id"}
        col.update_one({"_id": doc["_id"]}, {"$set": campos}, upsert=True)
        print("Registrado en la colección `fuentes` (_id='mgn').")
    except Exception as e:
        print(f"AVISO: no se pudo registrar en MongoDB ({e}).\n"
              "El JSON local quedó guardado; vuelve a correr cuando la base esté arriba.")
 
 
def descargar_mgn(url_directa: str | None = None, forzar: bool = False) -> Path:
    cfg = load_config()
    mgn = cfg["fuentes"]["mgn"]
    destino = ROOT / mgn["destino_local"]
    destino.mkdir(parents=True, exist_ok=True)
    zip_path = destino / NOMBRE_ZIP
 
    url_directa = (url_directa or os.environ.get("MGN_URL_DIRECTA")
                   or mgn.get("url_directa"))
 
    if zip_path.exists() and not forzar:
        print(f"Usando el ZIP que ya está en {zip_path}")
        url_registrada = url_directa or mgn["url_descarga"]
    elif url_directa:
        _bajar(url_directa, zip_path)
        url_registrada = url_directa
    else:
        otros = sorted(destino.glob("*.zip"))
        if otros:
            otros[0].replace(zip_path)
            print(f"Usando {otros[0].name} (renombrado a {NOMBRE_ZIP})")
            url_registrada = mgn["url_descarga"]
        else:
            raise FileNotFoundError(
                "No hay ZIP del MGN y no se dio una URL directa.\n"
                f"  Opción A: descarga el MGN 2025 (nivel municipio) desde\n"
                f"            {mgn['url_descarga']}\n"
                f"            y deja el ZIP en {destino}\n"
                "  Opción B: define MGN_URL_DIRECTA en .env con el enlace directo del ZIP.")
 
    if not zipfile.is_zipfile(zip_path):
        raise ValueError(f"{zip_path} no es un ZIP válido (¿se descargó una página web?).")
 
    checksum = _sha256(zip_path)
    _descomprimir(zip_path, destino / "extraido")
    print(f"SHA-256: {checksum}")
 
    doc = {
        "_id": "mgn",
        "nombre": mgn["descripcion"],
        "version": "MGN2025",
        "licencia": "Datos abiertos DANE (confirmar la licencia exacta en el geoportal)",
        "url_descarga": url_registrada,
        "periodo_imagenes": None,
        "crs_origen": _crs_origen(destino / "extraido"),
        "fecha_descarga": datetime.now(timezone.utc),
        "checksum_sha256": checksum,
        "archivo": NOMBRE_ZIP,
        "tamano_bytes": zip_path.stat().st_size,
    }
    # copia local de respaldo (la fecha como texto para poder guardarla en JSON)
    copia = dict(doc, fecha_descarga=doc["fecha_descarga"].isoformat())
    (destino / "fuente_mgn.json").write_text(
        json.dumps(copia, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Metadatos guardados en {destino / 'fuente_mgn.json'}")
 
    _registrar_en_mongo(cfg, doc)
    return destino / "extraido"
 
 
if __name__ == "__main__":
    descargar_mgn()