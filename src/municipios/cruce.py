"""t02 (Jorge): cruza la capa municipal del MGN con MunicipiosPDET.xlsx.

Debe:
  - Leer config.yaml -> fuentes.pdet.archivo (MunicipiosPDET.xlsx).
  - Rellenar los códigos DANE a 5 dígitos (los de Antioquia pierden el 0 inicial
    al venir como número en el Excel, p.ej. 5045 -> "05045").
  - Devolver la capa del MGN filtrada a los municipios que cruzaron.
"""


def cruzar_con_pdet():
    raise NotImplementedError


if __name__ == "__main__":
    cruzar_con_pdet()
