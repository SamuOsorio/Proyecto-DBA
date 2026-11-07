# Proyecto-DBA

Potencial solar en techos de los municipios PDET. Proyecto final del curso
Administración de Bases de Datos (DBA), Pontificia Universidad Javeriana — 2026-30.

Estima, para cada uno de los 170 municipios PDET, el número de edificaciones y
el área total de techos disponible para paneles solares, comparando fuentes
abiertas de huellas de edificios (Google Open Buildings y Microsoft Building
Footprints) sobre los límites municipales oficiales del DANE (MGN 2025), con
MongoDB e índices espaciales.

El diseño completo (plan de implementación, diagrama E-R y diccionario de
datos) está en [`Entrega 1/Entrega 1.pdf`](<Entrega 1/Entrega 1.pdf>).

## Cómo correr el proyecto

Requisitos: Docker + Docker Compose, Python 3.12.

```bash
cp .env.example .env            # ajustar usuario/contraseña si hace falta
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

make up                         # levanta MongoDB 8 en Docker
make schema                     # crea las colecciones con $jsonSchema (semana 1)
make municipios                 # descarga, valida y carga los municipios PDET (semana 2)
```

`make down` apaga el contenedor. `make shell` abre `mongosh` contra la base.

## Estructura del repositorio

```
src/
  common/      conexión a Mongo y carga de config.yaml, compartido por todas las fases
  municipios/  semana 2: límites PDET, un archivo por tarea (ver tabla abajo)
  edificios/   semana 3: huellas de edificios
  analisis/    semana 4: asignación y agregación de resultados
config.yaml    parámetros de cada fase (CRS, fuentes, nombres de colecciones)
data/          datos crudos y procesados (no se versionan, ver .gitignore)
docs/          informes de cada entrega
notebooks/     EDA
```

### `src/municipios/` — quién hace qué

| Archivo | Tarea | Responsable |
|---|---|---|
| `descarga.py` | Descargar el MGN 2025 | Jorge |
| `cruce.py` | Cruzar con MunicipiosPDET.xlsx | Jorge |
| `verificacion.py` | Verificar los 170 municipios | Jorge |
| `geometria.py` | Validar/reparar geometrías y reproyectar | Maria Camila |
| `exportar.py` | Exportar `municipios_pdet.geojson` | Maria Camila |
| `schema.py` | Colecciones con `$jsonSchema` | Samuel |
| `carga.py` | Carga con PyMongo (upsert) | Samuel |
| `indices.py` | Índices `2dsphere` y `subregion_pdet.id` | Samuel |
| `evidencia.py` | `explain()` y `$geoIntersects` | Samuel |
| `mapa.py` | Mapa de control | Jose Eduardo |
| `calidad.py` | Chequeo de tamaño BSON | Jose Eduardo |

`run.py` encadena todo en orden (es lo que corre `make municipios`). `MunicipiosPDET.xlsx`
no está en el repo todavía — hay que conseguirlo de los recursos del curso y ponerlo
en `data/raw/` antes de que Jorge pueda empezar `cruce.py`.

## Flujo de trabajo del equipo

- Una rama y un pull request por persona y por tarea. Cada PR lo aprueba
  alguien de otro frente antes de hacer merge a `main`.
- Commits distribuidos durante la semana, no todo de último momento.
- Cualquier integrante puede salir a sustentar: todos deben poder explicar el
  flujo completo, no solo su parte.
