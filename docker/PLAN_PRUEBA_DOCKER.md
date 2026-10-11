# Plan de prueba: dockerizar Monit_Servers_V2 en la VM de Ubuntu Server

> Paso a paso de todo lo que se va a hacer para validar el paso 13 del ROADMAP (migración del
> stack central a Docker) **en la VM de prueba**, antes de tocar DEVELOP. Sigue las convenciones
> ya documentadas en [`CONVENCIONES_QUANTUM.md`](CONVENCIONES_QUANTUM.md).

## Objetivo

Confirmar que Postgres + backend/dashboard + ingesta corren correctamente dentro de Docker, sin
arriesgar el despliegue actual (que sigue funcionando normal en tu máquina mientras tanto) ni
tocar datos reales de producción.

## Estado de partida

- VM lista: Ubuntu Server 22.04.5 LTS, `192.168.82.251` (**IP estática**, ver nota abajo), usuario
  `quantum` (uid 1000, ya en grupo `sudo`), 4 cores, 7.7 GB RAM, 47 GB libres en `/`. SSH activo.
- Backup disponible para la prueba: `bkp/Data_Base/monit_srv_011026.sql` (2026-10-01). Antes de
  usarlo conviene generar uno fresco con `db/respaldar.py` para tener datos más recientes.
- La VM está en red **Bridged** (misma LAN física que tu máquina), pero **no tiene ZeroTier** —
  no alcanza DEVELOP/MINI_LENOVO/etc. directo. Eso solo importa para la Fase 4 (abajo).

## Arquitectura objetivo (dentro de la VM)

```
quantum-network (bridge, 192.168.60.0/24)
│
├── postgres        (imagen oficial postgres:16, volumen nombrado "pgdata")
│
└── backend         (nuestra imagen: FastAPI + dashboard estático + ingesta.py)
    - publica 127.0.0.1:8000 (igual que hoy en tu máquina, loopback-only por defecto)
    - monta desde el host: .env, inventario_servidores.yaml, ingesta/pendientes_offline/
```

Dos contenedores nada más para esta prueba — nada de Ofelia/scheduler todavía (eso es parte del
paso 13 real contra DEVELOP, no de esta prueba).

---

## Fase 1 — Preparar la VM (instalar Docker)

Script idempotente (se puede correr varias veces sin romper nada), siguiendo el mismo patrón que
`server-setup.sh` de Quantum pero sin las partes que no aplican (sin GPU, sin nginx, sin
S3/bootstrap de producto — eso es específico de `qface-server`):

1. Conectar por SSH a la VM (`ssh quantum@192.168.82.251`).
2. Actualizar paquetes: `sudo apt-get update`.
3. Instalar Docker Engine desde el **repositorio oficial de Docker** (no el paquete `docker.io` de
   Ubuntu, para tener una versión más reciente — mismo criterio que `server-setup.sh`):
   ```bash
   sudo install -m 0755 -d /etc/apt/keyrings
   curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
   sudo chmod a+r /etc/apt/keyrings/docker.gpg
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
     | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
   sudo apt-get update
   sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   ```
4. Agregar `quantum` al grupo `docker` (para no necesitar `sudo` en cada comando):
   ```bash
   sudo usermod -aG docker quantum
   ```
   Cerrar sesión SSH y volver a entrar para que el grupo tome efecto.
5. Configurar DNS explícito para Docker (`/etc/docker/daemon.json` con `8.8.8.8`/`1.1.1.1`) y
   reiniciar el servicio. **Necesario en la práctica**: sin esto, los contenedores heredan el
   `resolv.conf` "legacy" de systemd-resolved (las IPs de gateway de la red), que no siempre
   responde consultas DNS desde la red interna de Docker — se manifiesta como
   `Temporary failure resolving 'deb.debian.org'` en cualquier `apt-get` dentro de un build,
   aunque el propio host resuelva bien (vía su stub en `127.0.0.53`).
6. Verificar: `docker --version` y `docker compose version`.

Este script se guarda en [`docker/server-setup-vm.sh`](server-setup-vm.sh) (se crea en el momento
de ejecutar esta fase) para poder reusarlo si la VM se reinstala.

## Fase 2 — Armar los archivos de Docker en el repo

Todo nuevo, no modifica nada de lo que ya corre en tu máquina:

- **`docker/Dockerfile`**: imagen basada en `python:3.14-slim` (misma versión que pide el
  `Pipfile`), siguiendo el orden de capas de Quantum (deps antes que código):
  1. `WORKDIR /opt/quantumlabs/monit-servers-v2`
  2. `apt-get install` de lo mínimo necesario (sin paquetes de GPU/compilación pesada que no
     usamos) + limpieza de `/var/lib/apt/lists/*`
  3. Copiar `Pipfile`/`Pipfile.lock`, instalar con `pipenv install --system --deploy`
  4. Copiar el código (`backend/`, `dashboard/`, `ingesta/`, `db/schema.sql`) — **no** se copian
     `.env`, `inventario_servidores.yaml` ni `pendientes_offline/`, esos vienen del host como
     volúmenes (igual que `data/` en la plantilla de Quantum)
  5. `CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]`
- **`docker/docker-compose.yml`**:
  - Servicio `postgres` (imagen `postgres:16`, variables `POSTGRES_DB/USER/PASSWORD` desde
    `.env`, volumen nombrado `pgdata`, `db/schema.sql` montado en
    `/docker-entrypoint-initdb.d/` para que se aplique solo en el primer arranque).
  - Servicio `backend` (`build: ..`, variables `DB_HOST=postgres` + el resto desde `.env`,
    publica `127.0.0.1:8000:8000`, monta `inventario_servidores.yaml` y
    `ingesta/pendientes_offline/` desde el host, corre como el usuario `quantum` real
    (`user: "1000:1000"`, mismo uid que ya tiene `quantum` en la VM — así lo que el contenedor
    escriba en los volúmenes queda con dueño real, igual que en `start.sh` de Quantum).
  - Red `quantum-network` (bridge dedicada, mismo nombre que usa `qface-server` — por si más
    adelante DEVELOP tiene varios stacks Docker de Quantum que necesiten verse entre sí).
  - `restart: always` y `logging: {driver: json-file, options: {max-size: "1m"}}` en ambos
    servicios (igual que `start.sh`, evita que el log de Docker crezca sin límite).
- **`docker/.dockerignore`**: excluye `.git/`, `bkp/`, `__pycache__/`, `*.log`, `.env`,
  `inventario_servidores.yaml` (secretos reales nunca entran a la imagen).
- **`docker/.env.example`**: plantilla de las variables que necesita `docker-compose.yml`
  (`DB_NAME`, `DB_USER`, `DB_PASSWORD`) — análogo al `instance.env` de Quantum, pero para
  Compose. El real (`docker/.env`) no se versiona (cubierto por la regla `.env` del
  `.gitignore` raíz).

## Fase 3 — Prueba A: Docker + Postgres + backend + dashboard (sin red externa)

No depende de ZeroTier ni de los servidores reales — valida que el stack en sí funciona.

1. Generar un backup fresco en tu máquina: `python db/respaldar.py`.
2. Copiar el repo completo (o solo lo necesario) y el backup a la VM:
   ```bash
   scp -r . quantum@192.168.82.251:~/monit_servers_v2
   scp bkp/Data_Base/<archivo_mas_reciente>.sql quantum@192.168.82.251:~/restore.sql
   ```
3. En la VM: crear `.env.docker` real a partir del `.example`, con credenciales de prueba (no las
   de producción).
4. Levantar solo Postgres primero: `docker compose up -d postgres`.
5. Restaurar el backup dentro del contenedor:
   ```bash
   docker compose exec -T postgres psql -U <usuario> -d <db> < ~/restore.sql
   ```
6. Levantar el backend: `docker compose up -d backend`.
7. Validar:
   - `docker compose logs backend` sin errores.
   - `curl http://localhost:8000/api/servidores` desde la VM responde con el catálogo real.
   - Desde tu navegador (tu máquina está en la misma LAN que la VM): `http://192.168.82.251:8000`
     muestra el dashboard con los datos históricos reales de DEVELOP/MINI_LENOVO/etc.
   - El árbol de servidores, las tarjetas de estado, la gráfica histórica y la ficha de hardware
     se ven igual que en tu despliegue actual.
8. Botón "Actualizar" del dashboard: al no tener red hacia los servidores reales todavía
   (Fase 4), se espera que la parte "online" no traiga nada nuevo — no es un error, es lo
   esperado en esta fase.

## Fase 4 — Prueba B: ingesta "online" a través del túnel SSH ✅

Validada 2026-10-10: la ingesta online, incluido el mecanismo de relay/gateway (paso 14 del
ROADMAP), funciona de punta a punta dentro de Docker contra los servidores reales.

1. Usuario local `Quantum`/`Quantum18!` en la máquina Windows (ya tiene SSH Server activo,
   `192.168.82.116` en la misma LAN que la VM) — mismo patrón de credenciales que ya usa el
   inventario real.
2. Túnel SSH desde la VM hacia esa máquina, un `-L` por cada servidor activo del inventario:
   ```bash
   sshpass -p '...' ssh -N \
     -L 0.0.0.0:2201:192.168.192.205:22 \
     -L 0.0.0.0:2202:192.168.192.233:22 \
     -L 0.0.0.0:2203:192.168.192.193:22 \
     -L 0.0.0.0:2204:192.168.192.136:22 \
     -L 0.0.0.0:2205:192.168.194.15:22 \
     Quantum@192.168.82.116
   ```
3. `extra_hosts: ["host.docker.internal:host-gateway"]` en el servicio `backend` de
   `docker-compose.yml` (ya estaba desde la Fase 2).
4. Copia de prueba de `inventario_servidores.yaml` con los 5 servidores activos apuntando a
   `ip: host.docker.internal` y el puerto local correspondiente (2201-2205), montada en el
   contenedor en vez de la real — sin tocar `ingesta.py`/`relay.py`.
5. `POST /api/ingesta/ejecutar` → **12 archivos online cargados** + **20 archivos vía
   relay/gateway** (quantumdata→colima00/01/02, apiman-fase1→apiman-fase2/3), 191 filas nuevas
   reales en Postgres.

### Lecciones de esta fase

1. **El `-L` de SSH por defecto escucha solo en `127.0.0.1` del cliente (la VM)** — no alcanzable
   desde la red interna de Docker ni con `host.docker.internal`, aunque el *host-gateway* de
   Docker sí resuelva correctamente. Hay que bindear explícitamente a `0.0.0.0` en cada `-L`
   (`-L 0.0.0.0:puerto:destino:puerto_destino`) para que el túnel sea alcanzable desde contenedores.
2. **`ssh -f` no sobrevive si la sesión SSH que lo lanzó se cierra** (el backgrounding de `-f` no
   desprende la sesión por completo) — para un túnel persistente lanzado de forma no interactiva
   hace falta `setsid` (`setsid sh -c "ssh -N ..." < /dev/null > log 2>&1 &`), que sí desprende el
   proceso de la sesión que lo originó.

## Fase 5 — Checklist antes de dar la prueba por cerrada

- [x] Postgres arrancó limpio con el backup restaurado, sin errores de esquema (124,154 lecturas,
      12 servidores).
- [x] Backend/dashboard accesibles desde el navegador en `http://192.168.82.251:8000` — confirmado
      visualmente por el usuario.
- [x] Los endpoints principales responden con datos reales (`/servidores`,
      `/servidores/{nombre}/actual`).
- [x] El árbol de grupos, las tarjetas de estado, hardware y uso de disco se ven correctos
      (confirmado visualmente).
- [x] Ingesta online a través del túnel trae datos nuevos reales (12 online + 20 vía
      relay/gateway, ver Fase 4).
- [x] `docker compose down` y volver a `up` no pierde datos (el volumen `pgdata` persiste;
      124,154 filas intactas tras el ciclo).
- [x] Reiniciar la VM completa y volver a levantar los contenedores sin intervención manual —
      Postgres volvió solo (`restart: always` funcionó); el backend murió un momento porque tenía
      el puerto publicado en una IP que había cambiado (ver nota abajo), corregido y confirmado.

**Paso de prueba en la VM cerrado (2026-10-10).**

### Lecciones de esta prueba (aplican también cuando se migre a DEVELOP)

1. **DNS de Docker**: sin configurar `/etc/docker/daemon.json` con DNS explícito (`8.8.8.8`/
   `1.1.1.1`), los contenedores heredan el `resolv.conf` "legacy" de systemd-resolved (las IPs de
   gateway de la red), que no siempre responde consultas DNS desde la red interna de Docker —
   cualquier `apt-get`/`pip install` dentro de un build falla con `Temporary failure resolving`,
   aunque el propio host resuelva bien. Ya incorporado a `docker/server-setup-vm.sh`.
2. **IP estática, no DHCP**: la VM traía IP dinámica y cambió sola al reiniciar (de `.119` a
   `.117`), lo que además rompió el *binding* del puerto del backend (publicado en la IP vieja,
   que dejó de existir en el host). Se fijó `192.168.82.251` como IP estática vía netplan. En
   DEVELOP esto no debería repetirse si ya tiene IP fija asignada, pero vale la pena confirmarlo
   antes de migrar — un servidor de producción con IP dinámica tendría el mismo problema.

## Qué queda fuera de esta prueba (a propósito)

- Instalar o tocar nada en DEVELOP — eso es el paso 13 real, después de validar aquí.
- El scheduler Ofelia para la ingesta periódica dentro de Docker (decisión ya tomada en el
  ROADMAP, se implementa cuando migremos a DEVELOP).
- nginx/TLS como gateway público (no aplica hoy, ver `CONVENCIONES_QUANTUM.md`).
- Resolver los pendientes de decisión del paso 13 (credenciales SFTP del script de carga offline
  remota, etc.) — no bloquean esta prueba, se resuelven antes de migrar a DEVELOP en serio.

## Siguiente paso después de esta prueba

Si todo el checklist pasa, el mismo `Dockerfile`/`docker-compose.yml` (con las rutas/IPs
ajustadas) se usa para el despliegue real en DEVELOP — la prueba en la VM es justo para no tener
que descubrir problemas ahí por primera vez.
