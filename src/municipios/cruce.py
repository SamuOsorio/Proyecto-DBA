"""t02 (Jorge): cruza la capa municipal del MGN con MunicipiosPDET.xlsx.

Debe:
  - Leer config.yaml -> fuentes.pdet.archivo (MunicipiosPDET.xlsx).
  - Rellenar los códigos DANE a 5 dígitos (los de Antioquia pierden el 0 inicial
    al venir como número en el Excel, p.ej. 5045 -> "05045").
  - Devolver la capa del MGN filtrada a los municipios que cruzaron.

Además deja en data/processed/:
  cruce_tabla.csv           los 170 municipios PDET con la columna `cruzo`
  municipios_cruzados.gpkg  la capa filtrada (por si otro script la lee de disco)

Uso:  python -m src.municipios.cruce
"""
import re
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.common.config import ROOT, load_config


# ---------------------------------------------------------------- utilidades
def norm(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def codigo_5_digitos(serie: pd.Series) -> pd.Series:
    """5045, 5045.0 o '5045' -> '05045'."""
    s = serie.astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)
    return s.str.replace(r"\D", "", regex=True).str.zfill(5)


def _buscar_columna(df, incluye, excluye=(), nombre=""):
    for c in df.columns:
        n = norm(c)
        if all(k in n for k in incluye) and not any(k in n for k in excluye):
            return c
    raise ValueError(f"No encontré la columna de {nombre} en el Excel. "
                     f"Columnas: {list(df.columns)}")


# ------------------------------------------------------------------- Excel
def leer_pdet(cfg: dict | None = None) -> pd.DataFrame:
    """MunicipiosPDET.xlsx -> cod_mpio (5 dígitos), nombre_pdet, departamento_pdet, subregion_pdet."""
    cfg = cfg or load_config()
    ruta = ROOT / cfg["fuentes"]["pdet"]["archivo"]
    crudo = pd.read_excel(ruta, header=None, dtype=object)

    # el encabezado puede no estar en la primera fila: se busca la que dice "subregion"
    fila = next((i for i in range(min(15, len(crudo)))
                 if any("subreg" in norm(v) for v in crudo.iloc[i])), 0)
    df = crudo.iloc[fila + 1:].copy()
    df.columns = [str(c).strip() for c in crudo.iloc[fila]]
    df = df.dropna(how="all")

    c_cod = _buscar_columna(df, ["cod"], excluye=["dep", "dpto", "subreg"], nombre="código DANE")
    c_nom = _buscar_columna(df, ["municipio"], excluye=["cod"], nombre="municipio")
    c_dep = _buscar_columna(df, ["depart"], excluye=["cod"], nombre="departamento")
    c_sub = _buscar_columna(df, ["subreg"], nombre="subregión")

    df = df[df[c_cod].notna()]
    out = pd.DataFrame({
        "cod_mpio": codigo_5_digitos(df[c_cod]),
        "nombre_pdet": df[c_nom].astype(str).str.strip(),
        # celdas combinadas en Excel llegan vacías: se rellenan hacia abajo
        "departamento_pdet": df[c_dep].ffill().astype(str).str.strip(),
        "subregion_pdet": df[c_sub].ffill().astype(str).str.strip(),
    })
    return out.reset_index(drop=True)


# --------------------------------------------------------------------- MGN
def localizar_capa_municipal(carpeta: Path) -> Path:
    candidatos = [p for p in Path(carpeta).rglob("*.shp") if "mpio" in p.name.lower()]
    if not candidatos:
        raise FileNotFoundError(
            f"No hay un .shp de municipios (nombre con 'MPIO') en {carpeta}. "
            "¿Corriste antes descarga.py?")
    # preferir la capa político-administrativa y el nombre más corto
    return sorted(candidatos, key=lambda p: ("politico" not in p.name.lower(), len(p.name)))[0]


def leer_mgn(cfg: dict | None = None) -> gpd.GeoDataFrame:
    """Capa municipal del MGN con una columna extra `cod_mpio` (5 dígitos) y `nombre_mgn`."""
    cfg = cfg or load_config()
    carpeta = ROOT / cfg["fuentes"]["mgn"]["destino_local"]
    ruta = localizar_capa_municipal(carpeta)
    print(f"Capa MGN: {ruta.relative_to(ROOT) if ROOT in ruta.parents else ruta}")
    g = gpd.read_file(ruta)

    # El MGN cambia entre vigencias: nombres en mayúsculas (2020) o minúsculas (2025).
    # Se busca sin distinguir mayúsculas y se conservan los nombres originales.
    mapa = {c.lower(): c for c in g.columns}
    col = next((mapa[k] for k in ("mpio_cdpmp", "mpio_ccnct", "cod_mpio") if k in mapa), None)
    if col:
        g["cod_mpio"] = codigo_5_digitos(g[col])
    elif {"dpto_ccdgo", "mpio_ccdgo"} <= set(mapa):
        g["cod_mpio"] = (g[mapa["dpto_ccdgo"]].astype(str).str.zfill(2)
                         + g[mapa["mpio_ccdgo"]].astype(str).str.zfill(3))
    else:
        raise ValueError(f"No reconozco la columna de código en el MGN: {list(g.columns)}")

    nom = next((mapa[k] for k in ("mpio_cnmbr", "nombre_mpi", "nomb_mpio") if k in mapa), None)
    g["nombre_mgn"] = g[nom] if nom else None

    dup = g["cod_mpio"].duplicated(keep="first")
    if dup.any():
        print(f"AVISO: {int(dup.sum())} filas del MGN repiten código; se deja la primera.")
        g = g[~dup]
    return g


# ------------------------------------------------------------------- cruce
def tabla_cruce(cfg: dict | None = None):
    """Devuelve (tabla de los municipios PDET con columna `cruzo`, capa MGN completa)."""
    cfg = cfg or load_config()
    pdet = leer_pdet(cfg)
    mgn = leer_mgn(cfg)
    pdet["cruzo"] = pdet["cod_mpio"].isin(set(mgn["cod_mpio"]))
    return pdet, mgn


def cruzar_con_pdet() -> gpd.GeoDataFrame:
    cfg = load_config()
    pdet, mgn = tabla_cruce(cfg)

    filtrada = mgn.merge(pdet.drop(columns="cruzo"), on="cod_mpio", how="inner")
    filtrada = gpd.GeoDataFrame(filtrada, geometry="geometry", crs=mgn.crs)

    salida = ROOT / "data" / "processed"
    salida.mkdir(parents=True, exist_ok=True)
    pdet.to_csv(salida / "cruce_tabla.csv", index=False, encoding="utf-8-sig")
    filtrada.to_file(salida / "municipios_cruzados.gpkg", driver="GPKG")

    print(f"Cruzaron {int(pdet['cruzo'].sum())} de {len(pdet)} municipios PDET.")
    return filtrada


if __name__ == "__main__":
    cruzar_con_pdet()
