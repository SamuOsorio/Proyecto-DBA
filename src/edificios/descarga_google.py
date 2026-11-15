"""Descarga de Google Open Buildings v3 (celdas S2 de nivel 4 que tocan Colombia).

Debe:
  - Identificar las celdas S2 que tocan Colombia y bajarlas a
    config.yaml -> fuentes.google_open_buildings.destino_local.
  - Registrar URL, versión, licencia, fecha y SHA-256 en la colección
    `fuentes` (_id="google").

Cómo se eligen las celdas: Google publica `score_thresholds_s2_level_4.csv`, con
una fila por celda (s2_token + su polígono en WKT + building_count). Se cruzan esos
polígonos con el MGN y se bajan solo las celdas que tocan el territorio.

Uso:
  python -m src.edificios.descarga_google --listar      # celdas y tamaño, sin bajar
  python -m src.edificios.descarga_google               # descarga (reanuda si se corta)
  python -m src.edificios.descarga_google --solo-pdet   # solo celdas que tocan los 170 municipios
"""
import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import shapely

from src.common.config import ROOT, load_config, mongo_uri
from src.municipios.cruce import leer_mgn, leer_pdet

# GOOGLE_OB_BASE permite apuntar a un espejo (o a un servidor local para pruebas)
BASE = os.environ.get("GOOGLE_OB_BASE", "https://storage.googleapis.com/open-buildings-data/v3")
URL_UMBRALES = f"{BASE}/score_thresholds_s2_level_4.csv"
URL_CARPETA = f"{BASE}/polygons_s2_level_4_gzip/"
URL_CELDA = URL_CARPETA + "{token}_buildings.csv.gz"
MANIFIESTO = "descarga_google.json"
REINTENTOS = 5


# ---------------------------------------------------------------- utilidades
def _destino(cfg: dict) -> Path:
    d = ROOT / cfg["fuentes"]["google_open_buildings"]["destino_local"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def _tamano_remoto(url: str):
    try:
        r = requests.head(url, timeout=30, allow_redirects=True)
        if r.ok and "Content-Length" in r.headers:
            return int(r.headers["Content-Length"])
    except requests.RequestException:
        pass
    return None


def _bajar(url: str, destino: Path) -> None:
    """Descarga en streaming a `<archivo>.part` y reanuda si se corta la conexión."""
    parcial = destino.with_name(destino.name + ".part")
    for intento in range(1, REINTENTOS + 1):
        try:
            pos = parcial.stat().st_size if parcial.exists() else 0
            cab = {"Range": f"bytes={pos}-"} if pos else {}
            with requests.get(url, stream=True, headers=cab, timeout=(30, 120)) as r:
                if r.status_code != 416:  # 416: el .part ya estaba completo
                    r.raise_for_status()
                    modo = "ab" if (pos and r.status_code == 206) else "wb"
                    with parcial.open(modo) as f:
                        for bloque in r.iter_content(8 * 1024 * 1024):
                            f.write(bloque)
            break
        except requests.RequestException as e:
            if intento == REINTENTOS:
                raise
            print(f"  reintento {intento}/{REINTENTOS} ({e})")
            time.sleep(5 * intento)
    parcial.replace(destino)


def _leer_manifiesto(destino: Path) -> dict:
    ruta = destino / MANIFIESTO
    if not ruta.exists():
        return {}
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return {a["token"]: a for a in datos.get("archivos", [])}


def _guardar_manifiesto(destino: Path, archivos: list, ambito: str) -> dict:
    datos = {
        "fecha": datetime.now(timezone.utc).isoformat(),
        "ambito": ambito,
        "celdas": [a["token"] for a in archivos],
        "archivos": archivos,
        "bytes_total": sum(a["bytes"] for a in archivos),
        "segundos_total": round(sum(a.get("segundos", 0) for a in archivos), 1),
    }
    (destino / MANIFIESTO).write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return datos


# ------------------------------------------------------------ celdas S2
def celdas_que_tocan(cfg: dict | None = None, solo_pdet: bool = False) -> pd.DataFrame:
    """Celdas S2 nivel 4 cuyo polígono toca Colombia (o solo los municipios PDET)."""
    cfg = cfg or load_config()
    destino = _destino(cfg)
    csv = destino / "score_thresholds_s2_level_4.csv"
    if not csv.exists():
        print(f"Bajando tabla de celdas: {URL_UMBRALES}")
        _bajar(URL_UMBRALES, csv)

    t = pd.read_csv(csv, dtype={"s2_token": str})
    faltan = {"s2_token", "geometry"} - set(t.columns)
    if faltan:
        raise ValueError(f"A la tabla de celdas le faltan columnas {faltan}: {list(t.columns)}")
    celdas = gpd.GeoDataFrame(
        t.drop(columns="geometry"),
        geometry=shapely.from_wkt(t["geometry"].to_numpy()),
        crs="EPSG:4326")

    mgn = leer_mgn(cfg).to_crs("EPSG:4326")
    if solo_pdet:
        mgn = mgn[mgn["cod_mpio"].isin(set(leer_pdet(cfg)["cod_mpio"]))]
    zona = mgn.geometry.union_all()

    sel = celdas.geometry.intersects(zona)
    if "building_count" in celdas.columns:
        sel &= celdas["building_count"].fillna(0) > 0  # celdas sin edificios no tienen archivo
    elegidas = celdas[sel]
    cols = [c for c in ("s2_token", "building_count") if c in elegidas.columns]
    return elegidas[cols].sort_values("s2_token").reset_index(drop=True)


# ---------------------------------------------------------------- registro
def _registrar_en_mongo(cfg: dict, doc: dict) -> None:
    try:
        from pymongo import MongoClient
        cliente = MongoClient(mongo_uri(cfg), serverSelectionTimeoutMS=5000)
        col = cliente[cfg["database"]["name"]][cfg["database"]["collections"]["fuentes"]]
        campos = {k: v for k, v in doc.items() if k != "_id"}
        col.update_one({"_id": doc["_id"]}, {"$set": campos}, upsert=True)
        print("Registrado en la colección `fuentes` (_id='google').")
    except Exception as e:
        print(f"AVISO: no se pudo registrar en MongoDB ({e}).\n"
              "El manifiesto local quedó guardado; vuelve a correr cuando la base esté arriba.")


# --------------------------------------------------------------- principal
def descargar_google(solo_pdet: bool = False, forzar: bool = False, listar: bool = False):
    cfg = load_config()
    destino = _destino(cfg)
    ambito = "municipios PDET" if solo_pdet else "Colombia"

    celdas = celdas_que_tocan(cfg, solo_pdet)
    tokens = celdas["s2_token"].tolist()
    print(f"{len(tokens)} celdas S2 (nivel 4) tocan {ambito}: {', '.join(tokens)}")

    if listar:
        total = 0
        for token in tokens:
            tam = _tamano_remoto(URL_CELDA.format(token=token))
            total += tam or 0
            print(f"  {token}: {tam / 1e9:.2f} GB" if tam else f"  {token}: tamaño desconocido")
        print(f"Total aproximado: {total / 1e9:.2f} GB (comprimido)")
        return None

    previos = _leer_manifiesto(destino)
    archivos = []
    for i, token in enumerate(tokens, 1):
        url = URL_CELDA.format(token=token)
        ruta = destino / f"{token}_buildings.csv.gz"
        previo = previos.get(token)
        if ruta.exists() and not forzar and previo and previo["bytes"] == ruta.stat().st_size:
            print(f"[{i}/{len(tokens)}] {ruta.name}: ya descargado, se reutiliza")
            archivos.append(previo)
            continue
        if ruta.exists() and not forzar and not previo:
            print(f"[{i}/{len(tokens)}] {ruta.name}: ya existe, se calcula su SHA-256")
            seg = 0.0
        else:
            esperado = _tamano_remoto(url)
            print(f"[{i}/{len(tokens)}] Descargando {ruta.name}"
                  + (f" ({esperado / 1e9:.2f} GB)" if esperado else ""))
            t0 = time.perf_counter()
            _bajar(url, ruta)
            seg = time.perf_counter() - t0
            if esperado and ruta.stat().st_size != esperado:
                raise IOError(f"{ruta.name}: tamaño {ruta.stat().st_size} distinto del esperado {esperado}")
        archivos.append({
            "token": token, "archivo": ruta.name, "url": url,
            "bytes": ruta.stat().st_size, "sha256": _sha256(ruta),
            "segundos": round(seg, 1),
        })
        _guardar_manifiesto(destino, archivos, ambito)  # no perder progreso si se corta

    datos = _guardar_manifiesto(destino, archivos, ambito)
    # un solo SHA-256 para la fuente: hash del manifiesto "token:sha256" ordenado
    resumen = "\n".join(f"{a['token']}:{a['sha256']}" for a in sorted(archivos, key=lambda a: a["token"]))
    checksum = hashlib.sha256(resumen.encode()).hexdigest()

    doc = {
        "_id": "google",
        "nombre": "Google Open Buildings v3 (polígonos)",
        "version": "v3",
        "licencia": "CC BY-4.0 y ODbL v1.0 (a elección del usuario)",
        "url_descarga": URL_CARPETA,
        "periodo_imagenes": "Inferencia de mayo de 2023",
        "crs_origen": "EPSG:4326",
        "fecha_descarga": datetime.now(timezone.utc),
        "checksum_sha256": checksum,
        "archivos": [{k: a[k] for k in ("token", "archivo", "bytes", "sha256")} for a in archivos],
        "tamano_bytes": datos["bytes_total"],
    }
    print(f"{len(archivos)} archivos, {datos['bytes_total'] / 1e9:.2f} GB. SHA-256 de la fuente: {checksum}")
    _registrar_en_mongo(cfg, doc)
    return datos


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Descarga Google Open Buildings v3")
    p.add_argument("--listar", action="store_true", help="solo muestra celdas y tamaño")
    p.add_argument("--solo-pdet", action="store_true", help="celdas que tocan solo los 170 municipios PDET")
    p.add_argument("--forzar", action="store_true", help="vuelve a bajar aunque ya exista")
    a = p.parse_args()
    descargar_google(solo_pdet=a.solo_pdet, forzar=a.forzar, listar=a.listar)
