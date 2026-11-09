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
| 3 | Huellas de edificios (Google y Microsoft) | Pendiente |
| 4 | Asignación por centroide, resultados e informe | Pendiente |

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

Datos versionados a propósito (el resto de `data/` está en `.gitignore`):
`data/raw/MunicipiosPDET.xlsx` (insumo pequeño y estable) y
`data/processed/municipios_pdet.geojson` (salida final, ~37 MB), para que nadie
tenga que volver a descargar el MGN solo para probar su parte.

## Flujo de trabajo del equipo

- Una rama y un pull request por persona y por tarea. Cada PR lo aprueba
  alguien de otro frente antes de hacer merge a `main`.
- Commits distribuidos durante la semana, no todo de último momento.
- Cualquier integrante puede salir a sustentar: todos deben poder explicar el
  flujo completo, no solo su parte.
