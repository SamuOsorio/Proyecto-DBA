.PHONY: up down logs shell schema municipios edificios analisis all

up:
	docker compose up -d
	docker compose exec mongodb mongosh --quiet --eval "db.adminCommand('ping')" || sleep 3

down:
	docker compose down

logs:
	docker compose logs -f mongodb

shell:
	docker compose exec mongodb mongosh "$${MONGO_URI}"

# Crea las colecciones con validación $jsonSchema (también la corre `make municipios`)
schema:
	python3 -m src.municipios.schema

# Semana 2: descarga MGN, cruza con PDET, valida/repara geometrías, carga e indexa municipios
municipios:
	python3 -m src.municipios.run

# Semana 3: descarga, prefiltra y carga huellas de edificios
edificios:
	python3 -m src.edificios.run

# Semana 4: asigna edificios a municipios y agrega resultados
analisis:
	python3 -m src.analisis.run

all: up municipios edificios analisis
