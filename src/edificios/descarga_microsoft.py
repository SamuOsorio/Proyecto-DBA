"""e05 (Maria Camila): descarga Microsoft Building Footprints para Colombia.

Qué hace:
  1. Baja el índice `dataset-links.csv` de Microsoft y deja solo las
     particiones (quadkey de nivel 9) de Colombia.
  2. Se queda con las que tocan algún municipio PDET: el resto del país no se
     descarga.
  3. Baja esas particiones en paralelo a config.yaml ->
     fuentes.microsoft_building_footprints.destino_local, sin repetir las que
     ya están.
  4. Calcula el SHA-256 de cada archivo (manifest.csv) y uno global, y registra
     la fuente en `fuentes` (_id="microsoft") y la etapa en `bitacora_cargas`.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
import shapely
from shapely.geometry import box

from src.common.config import ROOT, load_config, mongo_uri
from src.edificios.comun import cargar_union_pdet

LICENCIA = "ODbL 1.0 (Open Data Commons Open Database License)"
PERIODO = "Imágenes Bing Maps 2014-2021 (según el enunciado del proyecto)"


def _limites_quadkey(quadkey: str) -> tuple[float, float, float, float]:
    """(lon_min, lat_min, lon_max, lat_max) de una tesela quadkey (Web Mercator)."""
    x = y = 0
    for c in quadkey:
        d = int(c)
        x = (x << 1) | (d & 1)
        y = (y << 1) | ((d >> 1) & 1)
    n = 2 ** len(quadkey)

    def lat(yy: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))

    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def _bajar(url: str, destino: Path, intentos: int = 4) -> None:
    parcial = destino.with_suffix(destino.suffix + ".part")
    for intento in range(1, intentos + 1):
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with parcial.open("wb") as f:
                    for bloque in r.iter_content(chunk_size=1024 * 1024):
                        f.write(bloque)
            parcial.replace(destino)
            return
        except requests.RequestException:
            if intento == intentos:
                raise
            time.sleep(2 * intento)


def _descargar_una(args: tuple[dict, Path]) -> dict:
    fila, carpeta = args
    destino = carpeta / f"quadkey_{fila['QuadKey']}.csv.gz"
    if not destino.exists() or destino.stat().st_size == 0:
        _bajar(fila["Url"], destino)
    return {"quadkey": fila["QuadKey"], "url": fila["Url"], "archivo": destino.name,
            "bytes": destino.stat().st_size, "sha256": _sha256(destino)}


def _registrar_en_mongo(cfg: dict, doc: dict, bitacora: dict) -> None:
    try:
        from pymongo import MongoClient
        cliente = MongoClient(mongo_uri(cfg), serverSelectionTimeoutMS=5000)
        db = cliente[cfg["database"]["name"]]
        campos = {k: v for k, v in doc.items() if k != "_id"}
        db[cfg["database"]["collections"]["fuentes"]].update_one(
            {"_id": doc["_id"]}, {"$set": campos}, upsert=True)
        db[cfg["database"]["collections"]["bitacora_cargas"]].insert_one(bitacora)
        print("Registrado en `fuentes` (_id='microsoft') y en `bitacora_cargas`.")
    except Exception as e:  # no debe tumbar la descarga
        print(f"AVISO: no se pudo registrar en MongoDB ({e}).\n"
              "El JSON local quedó guardado; vuelve a correr cuando la base esté arriba.")


def descargar_microsoft(forzar_indice: bool = False) -> Path:
    cfg = load_config()
    ms = cfg["fuentes"]["microsoft_building_footprints"]
    carpeta = ROOT / ms["destino_local"]
    carpeta.mkdir(parents=True, exist_ok=True)
    inicio = datetime.now(timezone.utc)

    # 1) Índice de Microsoft, solo Colombia
    indice = carpeta / "dataset-links.csv"
    if forzar_indice or not indice.exists():
        print(f"Descargando el índice {ms['url_indice']}")
        _bajar(ms["url_indice"], indice)
    with indice.open(encoding="utf-8") as f:
        colombia = [r for r in csv.DictReader(f) if r["Location"] == ms["region"]]
    print(f"[microsoft] {len(colombia)} particiones de {ms['region']} en el índice.")

    # 2) Solo las que tocan algún municipio PDET
    union = cargar_union_pdet(cfg)
    elegidas = [r for r in colombia if box(*_limites_quadkey(r["QuadKey"])).intersects(union)]
    print(f"[microsoft] {len(elegidas)} de {len(colombia)} particiones tocan municipios PDET.")

    # 3) Descarga en paralelo (las que ya existen no se repiten)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=cfg["edificios"]["descargas_paralelas"]) as pool:
        manifest = list(pool.map(_descargar_una, [(r, carpeta) for r in elegidas]))
    segundos = time.perf_counter() - t0
    manifest.sort(key=lambda m: m["quadkey"])

    with (carpeta / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["quadkey", "archivo", "bytes", "sha256", "url"])
        w.writeheader()
        w.writerows({k: m[k] for k in w.fieldnames} for m in manifest)

    # 4) Checksum global = SHA-256 de los SHA-256 de cada archivo, en orden
    checksum = hashlib.sha256("".join(m["sha256"] for m in manifest).encode()).hexdigest()
    total_bytes = sum(m["bytes"] for m in manifest)
    version = elegidas[0]["Url"].split("/global-buildings/")[1].split("/")[0] if elegidas else "desconocida"
    print(f"[microsoft] {len(manifest)} archivos, {total_bytes / 1e6:.1f} MB, "
          f"{segundos:.1f} s. SHA-256 global: {checksum}")

    doc = {
        "_id": "microsoft",
        "nombre": "Microsoft Building Footprints (Global ML Building Footprints), Colombia",
        "version": version,
        "licencia": LICENCIA,
        "url_descarga": ms["url_indice"],
        "periodo_imagenes": PERIODO,
        "crs_origen": "EPSG:4326",
        "fecha_descarga": datetime.now(timezone.utc),
        "checksum_sha256": checksum,
        "n_archivos": len(manifest),
        "tamano_bytes": total_bytes,
        "n_registros": None,
    }
    copia = dict(doc, fecha_descarga=doc["fecha_descarga"].isoformat())
    (carpeta / "fuente_microsoft.json").write_text(
        json.dumps(copia, ensure_ascii=False, indent=2), encoding="utf-8")

    _registrar_en_mongo(cfg, doc, {
        "fuente_id": "microsoft", "etapa": "descarga",
        "inicio": inicio, "fin": datetime.now(timezone.utc),
        "registros_ok": len(manifest), "registros_error": 0,
        "parametros": {"particiones_colombia": len(colombia),
                       "particiones_pdet": len(elegidas),
                       "bytes": total_bytes, "segundos": round(segundos, 1)},
    })
    return carpeta


if __name__ == "__main__":
    descargar_microsoft()
