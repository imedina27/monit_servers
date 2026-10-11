#!/bin/bash
# Fase 1 de docker/PLAN_PRUEBA_DOCKER.md: deja un host Ubuntu listo con Docker Engine + Compose.
# Idempotente (seguro de correr varias veces). Adaptado de server-setup.sh de qface-server
# (ver docker/CONVENCIONES_QUANTUM.md) sin las partes que no aplican aqui (GPU, nginx, S3).

set -euo pipefail

echo "==> Actualizando paquetes"
sudo apt-get update

if command -v docker >/dev/null 2>&1; then
    echo "Docker ya instalado ($(docker --version)), omitiendo instalacion."
else
    echo "==> Instalando Docker Engine desde el repositorio oficial de Docker"
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

if id -nG "$USER" | grep -qw docker; then
    echo "Usuario $USER ya esta en el grupo docker."
else
    echo "==> Agregando $USER al grupo docker"
    sudo usermod -aG docker "$USER"
    echo "Hace falta cerrar sesion SSH y volver a entrar para que el grupo surta efecto."
fi

# Sin esto, Docker hereda el resolv.conf "legacy" de systemd-resolved (las IPs de
# gateway de la red, ej. 192.168.x.1), que no siempre responde consultas DNS desde
# la red interna de un contenedor -- "Temporary failure resolving" en cualquier
# apt-get dentro de un build, aunque el propio host resuelva bien (via su stub
# 127.0.0.53). Forzar DNS publicos evita el problema sin importar la red del host.
if [ ! -f /etc/docker/daemon.json ]; then
    echo "==> Configurando DNS explicito para Docker (/etc/docker/daemon.json)"
    echo '{"dns": ["8.8.8.8", "1.1.1.1"]}' | sudo tee /etc/docker/daemon.json > /dev/null
    sudo systemctl restart docker
else
    echo "/etc/docker/daemon.json ya existe, no se toca."
fi

echo
echo "==> Verificacion"
docker --version
docker compose version
