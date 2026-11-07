"""t01 (Jorge): descarga el MGN 2025 del geoportal del DANE.

Debe:
  - Bajar la capa municipal a config.yaml -> fuentes.mgn.destino_local.
  - Calcular el checksum SHA-256 del archivo descargado.
  - Registrar en la colección `fuentes` (_id="mgn"): url_descarga, version,
    fecha_descarga, crs_origen (ver diccionario de datos, Entrega 1 sec. 5).
"""


def descargar_mgn() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    descargar_mgn()
