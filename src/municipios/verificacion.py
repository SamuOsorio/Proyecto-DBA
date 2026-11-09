"""t03 (Jorge): verifica que los 170 municipios PDET hayan cruzado correctamente.
 
Debe:
  - Comparar contra los 170 códigos de MunicipiosPDET.xlsx y reportar faltantes.
  - Confirmar que el resultado cubre 16 subregiones PDET y 19 departamentos.
  - Dejar una tabla de control (cuántos cruzaron, cuáles no y por qué).
 
Deja en data/processed/: verificacion_control.csv y verificacion_sin_cruce.csv.
Si algo no coincide lanza un error (así `make municipios` se detiene antes de cargar).
 
Uso:  python -m src.municipios.verificacion
"""
import pandas as pd
 
from src.common.config import ROOT, load_config
from src.municipios.cruce import norm, tabla_cruce
 
ESPERADO = {"municipios": 170, "subregiones": 16, "departamentos": 19}
 
 
def _razon(fila, nombres_mgn: dict) -> str:
    parecidos = nombres_mgn.get(norm(fila["nombre_pdet"]))
    if parecidos:
        return (f"el MGN tiene '{fila['nombre_pdet']}' con código "
                f"{', '.join(parecidos)} (el Excel trae {fila['cod_mpio']})")
    return f"el código {fila['cod_mpio']} no existe en el MGN y el nombre tampoco coincide"
 
 
def verificar_cobertura(estricto: bool = True) -> pd.DataFrame:
    cfg = load_config()
    tabla, mgn = tabla_cruce(cfg)
    cruzaron = tabla[tabla["cruzo"]]
    sin_cruce = tabla[~tabla["cruzo"]].copy()
 
    nombres_mgn: dict = {}
    for cod, nom in zip(mgn["cod_mpio"], mgn["nombre_mgn"]):
        nombres_mgn.setdefault(norm(nom), []).append(cod)
    sin_cruce["razon"] = sin_cruce.apply(_razon, axis=1, nombres_mgn=nombres_mgn)
 
    repetidos = int(tabla["cod_mpio"].duplicated().sum())
    control = pd.DataFrame([
        ("Municipios en el Excel (códigos únicos)", ESPERADO["municipios"], tabla["cod_mpio"].nunique()),
        ("Códigos repetidos en el Excel", 0, repetidos),
        ("Municipios que cruzaron con el MGN", ESPERADO["municipios"], len(cruzaron)),
        ("Subregiones PDET en el resultado", ESPERADO["subregiones"], cruzaron["subregion_pdet"].nunique()),
        ("Departamentos en el resultado", ESPERADO["departamentos"], cruzaron["departamento_pdet"].nunique()),
    ], columns=["verificacion", "esperado", "obtenido"])
    control["ok"] = control["esperado"] == control["obtenido"]
 
    print("\n=== TABLA DE CONTROL ===")
    print(control.to_string(index=False))
    if len(sin_cruce):
        print(f"\nMunicipios que NO cruzaron ({len(sin_cruce)}):")
        print(sin_cruce[["cod_mpio", "nombre_pdet", "departamento_pdet", "razon"]]
              .to_string(index=False))
    else:
        print("\nTodos los municipios PDET cruzaron.")
 
    salida = ROOT / "data" / "processed"
    salida.mkdir(parents=True, exist_ok=True)
    control.to_csv(salida / "verificacion_control.csv", index=False, encoding="utf-8-sig")
    sin_cruce.to_csv(salida / "verificacion_sin_cruce.csv", index=False, encoding="utf-8-sig")
 
    if estricto and not control["ok"].all():
        raise RuntimeError("La verificación de los 170 municipios PDET falló; "
                           "revisa la tabla de control y data/processed/verificacion_sin_cruce.csv")
    print("\nVerificación OK")
    return control
 
 
if __name__ == "__main__":
    verificar_cobertura()