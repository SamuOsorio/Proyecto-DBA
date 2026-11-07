"""t12 (Samuel): evidencia de que el índice 2dsphere se está usando.

Debe:
  - Correr .explain() sobre una consulta espacial y confirmar la etapa IXSCAN
    (no COLLSCAN).
  - Correr una consulta $geoIntersects con un punto conocido (p.ej. la cabecera
    municipal de algún PDET) y verificar que devuelve el municipio correcto.
  - Guardar la salida para anexarla al informe de la Entrega 2.
"""


def mostrar_explain():
    raise NotImplementedError


if __name__ == "__main__":
    mostrar_explain()
