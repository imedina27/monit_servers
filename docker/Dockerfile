# syntax=docker/dockerfile:1.4
# Build desde la raiz del repo: docker build -f docker/Dockerfile .  (docker compose ya lo hace asi)
FROM python:3.14-slim

# uid:gid del usuario real del host que va a correr el contenedor (ver docker-compose.yml). Por
# defecto 1000, el de "quantum" en todos los servidores Quantum conocidos -- pero no es universal:
# una cuenta personal (ej. "imedina" en DEVELOP) puede tener un uid distinto, asignado por el
# sistema. Pasar HOST_UID/HOST_GID por build arg en vez de hornear 1000 a mano evita que el
# contenedor quede sin permiso de lectura sobre los secretos del host (inventario_servidores.yaml,
# etc., montados con el uid:gid real del dueño).
ARG HOST_UID=1000
ARG HOST_GID=1000

WORKDIR /opt/quantumlabs/monit-servers-v2

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

# Requirements antes que el codigo: si el codigo cambia pero no las dependencias,
# se reutiliza la capa de "pip install" (igual que el Dockerfile de qface-server).
COPY docker/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend backend
COPY dashboard dashboard
COPY ingesta ingesta
COPY comun comun

# ingesta/ necesita escritura propia para su log (ingesta/ingesta.log); pendientes_offline/ llega
# aparte como volumen del host y no depende de esto.
RUN chown ${HOST_UID}:${HOST_GID} ingesta

# .env, inventario_servidores.yaml y ingesta/pendientes_offline/ NUNCA se hornean en la imagen:
# llegan como variables de entorno / volumenes desde el host (ver docker-compose.yml).
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
