# Proyecto-DBA

Potencial solar en techos de los municipios PDET. Proyecto final del curso
Administración de Bases de Datos (DBA), Pontificia Universidad Javeriana — 2026-30.

Estima, para cada uno de los 170 municipios PDET, el número de edificaciones y
el área total de techos disponible para paneles solares, comparando fuentes
abiertas de huellas de edificios (Google Open Buildings y Microsoft Building
Footprints) sobre los límites municipales oficiales del DANE (MGN 2025), con
MongoDB e índices espaciales.

El diseño completo (plan de implementación, diagrama E-R y diccionario de
datos) está en [`Entrega 1/Entrega 1.pdf`](<Entrega 1/Entrega 1.pdf>). La carga de
municipios, los índices espaciales y su evidencia están en
[`Entrega 2/Entrega 2.pdf`](<Entrega 2/Entrega 2.pdf>), que también resume el plan y el
modelo de datos.

## Estado

| Semana | Fase | Estado |
|---|---|---|
| 1 | Infraestructura (Docker, esquema `$jsonSchema`) | Hecha |
| 2 | Límites PDET: 170 municipios cargados e indexados | Hecha (Entrega 2) |
| 3 | Huellas de edificios (Google y Microsoft): 2.694.786 y 1.761.048 edificios cargados e indexados, EDA en `notebooks/eda_edificios.ipynb` | Hecha (Entrega 3) |
| 4 | Asignación por centroide, `resultados` (170 documentos por fuente y umbral), sensibilidad, mapas y ranking | Hecha (Entrega 4) |
| Final | Informe técnico autocontenido para la UPME: [`Informe Final/Informe Final.pdf`](<Informe Final/Informe Final.pdf>) | Hecha |

## Cómo correr el proyecto

Requisitos: Docker + Docker Compose, Python 3.12 o superior.

```bash
cp .env.example .env            # ajustar usuario/contraseña si hace falta
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

make up                         # levanta MongoDB 8 en Docker
make schema                     # crea las colecciones con $jsonSchema (semana 1)
make municipios                 # descarga, valida y carga los municipios PDET (semana 2)
make edificios                  # descarga, limpia, carga e indexa edificios de Google y Microsoft (semana 3)
make analisis                   # asigna, agrega, exporta y genera tablas, mapas, ranking y potencial (semana 4)
```

`make all` corre todo lo anterior seguido, desde una base vacía. Para retomar el
análisis desde un paso: `python -m src.analisis.run --desde agregacion`. Para
rehacer solo las gráficas, los mapas y el ranking sin MongoDB (leen los CSV y el GeoJSON
versionados): `python -m src.analisis.run --solo-figuras`.

El MGN 2025 no tiene enlace directo y estable: descarga `MGN2025_MPIO_GRAFICO.zip`
del [geoportal del DANE](https://geoportal.dane.gov.co/servicios/descarga-y-metadatos/datos-geoestadisticos/?cod=111),
guárdalo como `data/raw/mgn_2025/MGN2025.zip` (o define `MGN_URL_DIRECTA` en `.env`).
El SHA-256 queda registrado en la colección `fuentes`.

`make down` apaga el contenedor. `make shell` abre `mongosh` contra la base.

## Estructura del repositorio

```
src/
  common/      conexión a Mongo y carga de config.yaml, compartido por todas las fases
  municipios/  semana 2: límites PDET, un archivo por tarea (ver tabla abajo)
  edificios/   semana 3: huellas de edificios
  analisis/    semana 4: asignación y agregación de resultados
config.yaml    parámetros de cada fase (CRS, fuentes, nombres de colecciones)
data/          datos crudos y procesados (ignorados por git, salvo las excepciones de abajo)
docs/          evidencia generada (mapa de control)
scripts/       utilidades sueltas (chequeo_bson.py)
Entrega N/     informe en LaTeX y PDF de cada entrega
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

`run.py` encadena todo en orden (es lo que corre `make municipios`).

### `src/analisis/` — quién hace qué (semana 4)

| Archivo | Tarea | Responsable |
|---|---|---|
| `asignacion.py` | Asignar cada edificio a su municipio (`$geoWithin` sobre `centroide`) | Jorge |
| `evidencia.py` | `explain()`: IXSCAN frente a COLLSCAN | Jorge |
| `validacion.py` | Validación con GeoPandas en 10 municipios | Jorge |
| `estilo.py` | Colores por fuente, formato y guardado de figuras | Jose Eduardo |
| `figuras_eda.py` | Las 4 figuras del EDA rehechas | Jose Eduardo |
| `agregacion.py` | `$group` + `$merge` a `resultados`, con verificación | Samuel |
| `sensibilidad.py` | Sensibilidad al umbral de confianza de Google | Samuel |
| `exportar.py` | CSV por municipio y subregión, tabla por subregión | Samuel |
| `mapas.py` | Mapas por fuente, de diferencia (D) y de % de techos | Maria Camila |
| `ranking.py` | Top 15 por área conservadora `min(A_G, A_M)` | Maria Camila |
| `run.py` | Encadena todo en orden (es lo que corre `make analisis`) | Maria Camila |

Las tablas y figuras de la semana 4 quedan en `Entrega 4/` y `Entrega 4/img/`.

Datos versionados a propósito (el resto de `data/` está en `.gitignore`):
`data/raw/MunicipiosPDET.xlsx` (insumo pequeño y estable) y
`data/processed/municipios_pdet.geojson` (salida final, ~37 MB), para que nadie
tenga que volver a descargar el MGN solo para probar su parte. En la semana 4 se
suman `resultados_municipio.csv`, `resultados_subregion.csv` y
`ranking_municipios.csv`, para rehacer mapas y ranking sin la base.

## Flujo de trabajo del equipo

- Una rama y un pull request por persona y por tarea. Cada PR lo aprueba
  alguien de otro frente antes de hacer merge a `main`.
- Commits distribuidos durante la semana, no todo de último momento.
- Cualquier integrante puede salir a sustentar: todos deben poder explicar el
  flujo completo, no solo su parte.
