"""t05+t06 (Maria Camila): valida, repara y reproyecta las geometrías municipales.

Debe:
  - Revisar is_valid de cada geometría; reparar con shapely.make_valid.
  - Llenar el subdocumento `calidad` {valida, reparada, n_vertices} del diccionario
    de datos (Entrega 1 sec. 5).
  - Reproyectar a WGS84 (EPSG:4326, orden [lon, lat]) para almacenamiento.
  - Calcular `area_km2` en EPSG:9377 (config.yaml -> crs.calculo_areas).
"""


def validar_y_reparar():
    raise NotImplementedError


def reproyectar_y_calcular_area():
    raise NotImplementedError


if __name__ == "__main__":
    validar_y_reparar()
    reproyectar_y_calcular_area()
