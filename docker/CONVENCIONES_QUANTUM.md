# Convenciones Docker de Quantum (de `qface-server`)

> Análisis de `~/Desktop/docker/` (plantilla real de `qface-server`, producto de reconocimiento
> facial de Quantum) para alinear la dockerización de Monit_Servers_V2 (paso 13 del ROADMAP) al
> mismo estilo. `qface-server` resuelve un problema bastante más complejo que el nuestro (GPU,
> licenciamiento, pesos de modelo en S3) — de ahí se separa qué aplica tal cual, qué se adapta, y
> qué no aplica.

## Estructura de carpetas observada

```
docker/
  Dockerfile
  requirements-qface.txt
  qlicense-product.json          # especifico de productos con licencia, no aplica aqui
  bin/
    build.sh                     # arma la imagen con buildx
    upload-bootstrap.sh          # publica bootstrap.sh/server-setup.sh/README a S3
    upload-weights.sh            # publica binarios grandes (pesos de modelo) a S3
  execution-template/
    .gitignore                   # excluye secretos y datos generados en vivo
    server-setup.sh              # deja un host Ubuntu listo desde cero (paquetes, Docker, usuario)
    data/
      bootstrap.sh                # extrae bin/config/start.sh de la imagen + descarga pesos
      start.sh                    # arma y corre el `docker run` real, lee instance.env
      README.md                   # documenta cada archivo de config
      config/
        instance.env               # version de imagen, usuario host, TZ, puerto
        db.conf / server.conf      # configuracion de negocio (JSON)
        log.conf                   # logging.config de Python
        nginx.template.conf        # plantilla de proxy inverso (opcional)
      bin/                        # wrappers de CLI sobre la API (un .sh por endpoint)
      home/, logs/, weights/      # carpetas que vive el host, vacias en el repo
      weights.sha256              # checksums de los binarios (no viajan en la imagen)
```

La idea central: **todo lo que pertenece a una instalación concreta (config, secretos, datos,
logs) vive en un `data/` montado desde el host — la imagen nunca lo trae**. `bootstrap.sh` extrae
una copia de referencia de `bin/`, `start.sh` y `config/*.conf` desde dentro de la propia imagen
(`docker cp`) la primera vez, así un host nuevo no necesita el repo, solo Docker y el script.

## Convenciones del `Dockerfile`

- `# syntax=docker/dockerfile:1.4` al inicio — habilita features de BuildKit (en su caso,
  `--mount=type=ssh` para clonar dependencias privadas; no lo necesitamos, nuestras deps son
  PyPI público).
- `WORKDIR /opt/quantumlabs/<producto>` — convención fija de dónde vive cada producto Quantum
  dentro del contenedor.
- Orden de capas pensado para cache: primero `requirements*.txt` + `pip install`, **después**
  `COPY` del código fuente — así un cambio de código no invalida la capa pesada de instalación de
  dependencias.
- `apt-get install` siempre con `DEBIAN_FRONTEND=noninteractive` + `rm -rf /var/lib/apt/lists/*
  /root/.cache/` al final de la misma capa RUN (no deja basura en la imagen).
- Crea usuarios/grupos de sistema (`quantum`, `ubuntu`) dentro de la imagen, pero el contenedor en
  realidad corre con el **UID:GID del usuario del host** pasado por `-u` en `docker run` — los
  usuarios de la imagen son solo referencia, no se usan directo.
- Un `CMD` simple al final (`python3 -m src.py.qface_server`).

## Convenciones de `start.sh` (cómo se corre el contenedor)

Esto es lo más directamente reusable:

- **Una sola fuente de verdad**: todo (versión de imagen, nombre de contenedor, usuario, TZ,
  puerto) vive en `instance.env`; `start.sh` solo lee de ahí, nunca hardcodea.
- **Nunca corre como root**: valida que `TARGET_USER`/`TARGET_GROUP` existan en el host *antes*
  de arrancar, y falla con un mensaje claro si no — nunca cae en correr como root por omisión.
  Corre con `-u uid:gid` real del host, así lo que el contenedor escribe en el volumen queda con
  dueño real, no con un UID numérico huérfano.
- **Red dedicada**: crea (si no existe) una red bridge propia, `quantum-network`
  (`192.168.0.0/24`) — para que varios contenedores Quantum en el mismo host se vean entre sí por
  nombre.
- **`--add-host=host.docker.internal:host-gateway`** — exactamente el mecanismo que ya habíamos
  planeado usar para el túnel SSH hacia los servidores vía ZeroTier. Confirma que es el patrón
  correcto a seguir aquí también.
- **Publicación de puertos conservadora por defecto**: la API se publica solo en
  `127.0.0.1:<PORT>` (loopback); exponerla más allá requiere una variable explícita
  (`BIND_EXTRA_IPS`, IPs literales separadas por coma). Documentan un detalle de seguridad
  importante que debemos recordar si algún día exponemos el dashboard más allá de `127.0.0.1`:
  **`ufw`/`iptables` no filtra puertos publicados por Docker** (el DNAT ocurre en `PREROUTING`,
  antes de la cadena `INPUT`) — `0.0.0.0` en un `-p` de Docker expone a internet sin que el
  firewall del host lo note.
- `--restart=always` y `--log-opt max-size=1m` (evita que el log de Docker crezca sin límite,
  aparte del propio rotado de la aplicación).
- `DOCKER_ARGS` se arma como **arreglo bash**, no como string concatenado — evita que una ruta
  con espacios rompa el comando.
- Detecta arquitectura (`uname -m`) para decidir flags de GPU (x86_64 vs. aarch64/Jetson) — no
  aplica a nuestro caso, no usamos GPU.

## Convenciones de `server-setup.sh` (dejar un host Ubuntu listo)

- **Idempotente de punta a punta**: cada paso revisa si ya está hecho antes de ejecutarlo (usuario
  ya existe, Docker ya instalado, etc.) — se puede correr varias veces sin romper nada.
- **Docker se instala desde el repositorio oficial de Docker** (`download.docker.com`), no desde
  el paquete `docker.io` de los repos de Ubuntu — nos da una versión más reciente y consistente
  entre hosts.
- Agrega al usuario correspondiente al grupo `docker` (para no necesitar `sudo docker` después).
- Crea el usuario/grupo de sistema (`quantum`) con su propio home, si no existe.
- Todo con `set -euo pipefail` al inicio — estándar en todos sus scripts de shell.

## Qué aplica a Monit_Servers_V2 y qué no

| Convención | ¿Aplica? | Nota |
|---|---|---|
| `data/` montado desde el host, nunca en la imagen | ✅ Sí | Ya es nuestro plan: `.env`, `inventario_servidores.yaml`, `pendientes_offline/`, volumen de Postgres — todo fuera de la imagen |
| Separar config de despliegue (`instance.env`) de config de negocio | ✅ Sí | Ya lo tenemos: `.env` (credenciales DB) vs. `backend/config.ini`/`ingesta/config.ini` |
| Correr como usuario real del host, nunca root | ✅ Sí | Mismo criterio que ya usamos en los `.service` de systemd (`User=quantum`) |
| Red bridge dedicada (`quantum-network`) | ✅ Sí, si DEVELOP va a tener más de un stack Docker de Quantum corriendo | Conviene unirnos a esa misma red si ya existe convención de compartirla en DEVELOP |
| `--add-host=host.docker.internal:host-gateway` | ✅ Sí | Es justo lo que usaremos para el túnel SSH hacia los servidores vía ZeroTier cuando probemos la ingesta "online" desde la VM |
| API en loopback por defecto + variable explícita para exponer más | ✅ Sí | Nuestro backend hoy ya está pensado para `127.0.0.1:8000` — mantenemos ese criterio al dockerizar |
| `server-setup.sh` tipo "deja el host listo" (instala Docker oficial, crea usuario, idempotente) | ✅ Sí, adaptado | Útil tener un script similar para dejar DEVELOP (y la VM de prueba) listos, sin GPU ni nginx |
| Orden de capas del Dockerfile (deps antes que código) | ✅ Sí | Buena práctica general, la aplicamos igual |
| `set -euo pipefail` + arreglos bash para argumentos | ✅ Sí | Convención a seguir en cualquier script nuevo que escribamos |
| Imagen base NVIDIA/CUDA, flags de GPU | ❌ No | No usamos GPU en el backend |
| Descarga de binarios pesados desde S3 (`quantum-weights`) | ❌ No | No tenemos modelos/pesos; nuestros "datos" son filas de Postgres, no archivos grandes |
| `qlicense-product.json` / sistema de licenciamiento | ❌ No | Herramienta interna, no es un producto licenciado a clientes |
| nginx + TLS + `x-api-key` como gateway público | ⏸ No por ahora | Patrón válido si algún día el dashboard se expone fuera de la red interna; no es el caso hoy |
| Cifrado de imágenes / tokens de acceso | ❌ No | Específico del manejo de datos biométricos de `qface-server` |
| `--mount=type=ssh` para dependencias privadas | ❌ No | Todas nuestras dependencias son PyPI público |

## Conclusión

El patrón de Quantum para Docker es sólido y bastante transferible en su columna vertebral
(usuario no-root con UID real del host, `data/` nunca horneado en la imagen, red dedicada,
`host.docker.internal` vía `host-gateway`, exposición de puertos conservadora por defecto,
scripts idempotentes con `set -euo pipefail`). La parte específica de `qface-server` (GPU, S3,
licenciamiento, cifrado) no aplica y no se replica. El `Dockerfile`/`docker-compose.yml` que
construyamos para el paso 13 va a seguir esta misma columna vertebral, simplificada a lo que
Monit_Servers_V2 realmente necesita: Postgres + backend/dashboard + ingesta, sin GPU ni
dependencias privadas.
