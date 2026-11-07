"""t10 (Samuel): carga municipios_pdet.geojson en MongoDB con PyMongo.

Debe:
  - Leer config.yaml -> municipios.salida_geojson (lo produce exportar.py).
  - Carga idempotente: upsert por `_id` (código DANE), no insert_many ciego.
  - Registrar la ejecución en `bitacora_cargas` (etapa="carga").
"""


def cargar_municipios():
    raise NotImplementedError


if __name__ == "__main__":
    cargar_municipios()
