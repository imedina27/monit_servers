# syntax=docker/dockerfile:1.4
# Build desde la raiz del repo: docker build -f docker/Dockerfile .  (docker compose ya lo hace asi)
FROM python:3.14-slim

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

# El contenedor corre como el usuario real del host (ver docker-compose.yml: user "1000:1000"),
# que es el uid:gid de "quantum" en todos los servidores Quantum conocidos hasta ahora (incluida
# esta VM de prueba). ingesta/ necesita escritura propia para su log (ingesta/ingesta.log);
# pendientes_offline/ llega aparte como volumen del host y no depende de esto.
RUN chown 1000:1000 ingesta

# .env, inventario_servidores.yaml y ingesta/pendientes_offline/ NUNCA se hornean en la imagen:
# llegan como variables de entorno / volumenes desde el host (ver docker-compose.yml).
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
