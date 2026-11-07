"""t07 (Jose Eduardo): chequeo de tamaño BSON por municipio antes de cargar.

Debe:
  - Medir el tamaño BSON de cada documento (bson.BSON.encode) a partir del
    GeoJSON que produce exportar.py (depende de t06, Maria Camila).
  - Señalar cualquier documento que se acerque o pase el límite de 16 MB de
    MongoDB (config.yaml -> municipios.max_bson_bytes) y documentar la tolerancia.
"""


def chequear_tamanos():
    raise NotImplementedError


if __name__ == "__main__":
    chequear_tamanos()
