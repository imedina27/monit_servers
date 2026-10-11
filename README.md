# Monitoreo de Temperaturas V2

Sistema centralizado para monitorear temperaturas de CPU/GPU de 15-20 servidores (Ubuntu y Windows), con base de datos PostgreSQL y dashboard web. Reemplaza el esquema anterior basado en CSV + Excel/Power Query (ver proyecto `Monit_Servers`).

## Estado

**En producción.** Monitoreando 11 servidores reales en 4 sitios (Quantum, AbInBev Zacatecas,
API/Manzanillo, C5i/Colima), stack central (Postgres + backend/dashboard + ingesta) corriendo en
Docker en DEVELOP. Sigue habiendo trabajo pendiente — ver [ROADMAP.md](ROADMAP.md) para el detalle
de lo que falta.

## Versionado

Se usa [SemVer](https://semver.org/lang/es/) (`vMAJOR.MINOR.PATCH`):

- **MAJOR**: cambios grandes de infraestructura (ej. migración a Docker).
- **MINOR**: funcionalidad nueva (ej. un sitio nuevo con relay, un endpoint nuevo).
- **PATCH**: fixes sin funcionalidad nueva.

Se sube de versión cada vez que se cierra un paso del [ROADMAP.md](ROADMAP.md) o se
pone en operación un sitio/cliente nuevo. El detalle legible de cada versión vive en
[CHANGELOG.md](CHANGELOG.md) (no reemplaza al `git log`, es un resumen orientado a
quien no siguió el trabajo commit por commit).

## Contexto / decisiones ya tomadas

- **Escala**: pensado para 15-20 servidores, mezcla de Ubuntu y Windows — hoy en operación real son 11, todos Ubuntu (el colector de Windows está en pausa, ver paso 4 del ROADMAP).
- **Base de datos**: PostgreSQL, containerizado con Docker desde el 2026-10-11 (antes corría nativo en la máquina Windows del usuario — ver sección de instalación). Se descartó SQLite por el volumen de servidores.
- **Riesgo técnico principal (si se retoma el colector de Windows)**: lectura de temperatura en Windows — WMI (`MSAcpi_ThermalZoneTemperature`) no es confiable en hardware moderno; se investigó **LibreHardwareMonitorLib** (requiere permisos de administrador) como alternativa, ver paso 4 del ROADMAP para el detalle de lo ya probado.

## Arquitectura (resumen)

- **Colectores**: un programa por SO (Ubuntu/Windows) que mide temperatura de CPU/GPU y uso de disco por punto de montaje en cada servidor.
- **Ingesta**: módulo único que descarga datos (modo online, vía scheduler, modo offline manual, o vía relay para sitios con compañeros) y los carga a Postgres — distingue temperatura de uso de disco por el nombre del archivo.
- **Backend/API**: capa que sirve agregaciones por hora/día/mes al dashboard, además del hardware/umbrales por servidor (administrados aparte, ver "Administrar un servidor").
- **Dashboard HTML**: gráfica de temperatura con zoom/desplazamiento, ficha técnica de hardware (chasis/CPU/GPU/RAM+DIMMs/discos/RAID), y uso de disco con un slider para navegar hasta 1 año de histórico. La sección "Estado actual" muestra la fecha de la lectura más reciente, y marca con `-- °C` cualquier sensor (CPU/GPU) cuya última lectura tenga más de 3h de antigüedad, para no mostrar un dato viejo como si fuera el valor presente.

## Instalación

### Colector Ubuntu (en cada servidor)

#### Requisitos previos (colector Ubuntu)

```bash
# Python 3 (normalmente ya viene instalado)
python3 --version

# CPU Intel/AMD: instalar lm-sensors
sudo apt install lm-sensors
sudo sensors-detect

# CPU ARM: no se requiere nada adicional, usa /sys/class/thermal del kernel

# GPU NVIDIA (opcional): verificar que el driver expone nvidia-smi
nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits
```

Para verificar qué método detectará el colector en ese servidor:

```bash
sensors                                    # CPU Intel/AMD
ls /sys/class/thermal/ | grep thermal_zone # CPU ARM
```

#### Paso 1 — Copiar los archivos al servidor

Copia la carpeta [`colector_ubuntu/`](colector_ubuntu/) (`monitor.py`, `config.ini`, `monit_servers_v2.service`) al servidor, por ejemplo a:

```text
/home/quantum/check/monit_servers_v2/colector_ubuntu/
```

(aún no hay repo remoto publicado; por ahora se copia vía `scp`/SFTP)

#### Paso 2 — Configurar `config.ini`

```ini
[monitoreo]
intervalo_minutos = 60

[almacenamiento]
directorio_salida = /home/quantum/check/monit_servers_v2/colector_ubuntu/lecturas
```

`directorio_salida` debe coincidir exactamente con el `directorio_remoto` que se configure para este servidor en el inventario central (paso 5) — si no coinciden, la ingesta nunca va a encontrar los archivos.

#### Paso 3 — Probar manualmente antes de instalar el servicio

```bash
cd /home/quantum/check/monit_servers_v2/colector_ubuntu
python3 monitor.py
```

Revisa `monitor.log`: debe indicar el método de CPU detectado (`lm-sensors` o `thermal_zones`) y que se están generando archivos en `lecturas/`. Detén con `Ctrl+C` una vez confirmado.

```bash
tail -f monitor.log
ls lecturas/
```

#### Paso 4 — Instalar el servicio systemd

```bash
# Editar si el usuario o las rutas reales difieren de 'quantum'/'check/monit_servers_v2'
nano monit_servers_v2.service

sudo cp monit_servers_v2.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable monit_servers_v2
sudo systemctl start monit_servers_v2
sudo systemctl status monit_servers_v2
```

> ⚠️ El nombre del servicio es `monit_servers_v2`, **distinto** del servicio viejo `monit_servers` (proyecto `Monit_Servers`), que puede seguir activo en el mismo servidor durante la transición. No lo detengas ni lo reemplaces sin confirmarlo antes — ambos pueden convivir sin conflicto porque usan rutas y unidades systemd separadas.
>
> ⚠️ **No agregues `StandardOutput=append:.../monitor.log` ni `StandardError=...` al `.service`** (la plantilla ya no los trae, a propósito). `systemd` crearía ese archivo él mismo como `root` antes de bajar privilegios al `User=` configurado, y como `monitor.py` también lo abre por su cuenta (`logging.basicConfig`), el segundo intento choca con el dueño `root` y el servicio entra en loop de reinicio con `PermissionError`. Si esto ya te pasó (el servicio queda `activating (auto-restart)` en vez de `active (running)`), corrígelo con `sudo chown quantum:quantum monitor.log` (ajusta el usuario) y `sudo systemctl restart monit_servers_v2`. Los errores no capturados por el log de aplicación quedan en `journalctl -u monit_servers_v2`.

Comandos útiles:

```bash
sudo systemctl start|stop|restart|status monit_servers_v2
journalctl -u monit_servers_v2 -f
```

#### Paso 5 — Agregar el servidor al inventario central

En la máquina donde corre la ingesta (ver [`ingesta/`](ingesta/)), agrega el servidor a `inventario_servidores.yaml` (copiar de [`inventario_servidores.yaml.example`](inventario_servidores.yaml.example) si aún no existe), con un `directorio_remoto` idéntico al `directorio_salida` del paso 2. Sin este paso la ingesta no sabe que el servidor existe y no va a descargar nada de él.

`activo: true` = servidor online (la ingesta se conecta por SSH automáticamente); `activo: false` = offline, sin alcance directo desde esta máquina (`ip`/`puerto`/`usuario`/`password` quedan vacíos) — la carga es manual vía `ingesta/pendientes_offline/<nombre_servidor>/` (ver sección de ingesta más abajo).

Agregar un servidor nuevo al YAML es automático: la próxima vez que corra la ingesta (botón "Actualizar" o el ciclo online) hace *upsert* en Postgres (tabla `servidores`/`grupos`), sin tocar la base de datos a mano. **Quitar uno no lo es** — la sincronización nunca borra, así que un servidor retirado del YAML se queda huérfano en la base de datos hasta que lo borres explícitamente con [`db/gestionar_servidor.py`](db/gestionar_servidor.py) (ver "Administrar un servidor" más abajo).

Una vez que el servidor ya existe en Postgres (después del primer `upsert` de arriba), usa el mismo script para darle de alta su hardware (chasis, CPU/GPU/RAM/discos/RAID, solo informativo) y sus umbrales de temperatura (verde/ámbar/rojo) — ver "Administrar un servidor".

### Relay (sitios offline con compañeros, o con gateway online)

Para sitios donde varios servidores se ven entre sí en su propia red, pero no todos son alcanzables directo desde la máquina central (ver [ROADMAP.md](ROADMAP.md), paso 14). Hay **4 escenarios posibles**; los dos primeros ya están cubiertos por "Colector Ubuntu" de arriba, sin nada adicional:

| Escenario | ¿Necesita `relay/`? | `activo` en el inventario central | Carga a Postgres |
| --- | --- | --- | --- |
| Servidor simple, online | No | `true` | Automática (ingesta por SSH directo) |
| Servidor simple, offline (sin compañeros) | No | `false` | Manual, vía `pendientes_offline/<nombre>/` |
| **Sitio 100% offline con un "hub"** (ej. AbInBev) | Sí, en el hub | `false` (ni el hub ni sus compañeros son alcanzables) | Manual — alguien trae el bundle consolidado del hub |
| **Sitio con gateway online** (ej. API/Manzanillo) | Sí, en el gateway | `true` en el gateway, `false` en cada compañero | Automática — la ingesta baja sola lo que el gateway recolectó |

La diferencia entre los dos últimos es solo si el servidor que corre `relay.py` (el "hub"/"gateway") es alcanzable o no desde la máquina central — el `relay.py` y el flujo de instalación son **idénticos** en ambos casos.

#### Paso 1 — Instalar el colector en cada compañero

Igual que "Colector Ubuntu" arriba (pasos 1-4), en cada servidor compañero del sitio. Estos normalmente **no** son alcanzables directo desde la máquina central (por eso necesitan el relay) — despliega los archivos por el medio que tengas disponible hacia ese sitio (USB, u otro servidor del mismo sitio que sí tenga acceso).

#### Paso 2 — Instalar `relay.py` en el hub/gateway

Requisitos: a diferencia del colector (stdlib puro), `relay.py` necesita `paramiko`/`pyyaml`:

```bash
python3 -c "import paramiko, yaml" || sudo apt install python3-paramiko python3-yaml
```

> ⚠️ En Ubuntu 23.04+/Debian 12+, `pip3 install paramiko pyyaml` falla con `error: externally-managed-environment` (PEP 668). Usa el paquete de `apt` de arriba — instala directo en el Python del sistema, el mismo que usa `ExecStart=/usr/bin/python3`, sin tocar nada más. Si el paquete de `apt` no alcanza (versión vieja), la alternativa es `pip3 install --break-system-packages paramiko pyyaml`, o un venv dedicado apuntando `ExecStart` a `<venv>/bin/python3`.
>
> ⚠️ Si el servidor usa **conda**, verifica que el `python3` que vas a poner en `ExecStart` del `.service` sea el mismo donde quedaron instalados esos paquetes (`<python3_elegido> -c "import paramiko, yaml"`) — si conda estaba activo cuando corriste el `pip install`, pueden haber quedado invisibles para `/usr/bin/python3` del sistema. Ajusta `ExecStart` al Python de conda si hace falta.

Copia la carpeta [`relay/`](relay/) (`relay.py`, `config.ini`, `monit_servers_v2_relay.service`) al hub, por ejemplo a `/home/quantum/monit_servers_v2/relay/`.

Crea `companeros.yaml` a partir de [`companeros.yaml.example`](relay/companeros.yaml.example) — **este archivo vive solo en el hub, nunca se sube a git** (ver `.gitignore`), con las credenciales reales de cada compañero de este sitio (usuario/password, o deja `password` vacío si el sitio usa llaves SSH sin contraseña, como en AbInBev — verifica antes con `ssh -v <companero> exit` y `ssh-keygen -y -f <ruta_llave>` que la llave por defecto no tenga passphrase, para que funcione igual corriendo como servicio que a mano):

```yaml
companeros:
  - nombre: <nombre_companero>          # debe coincidir con el inventario central (paso 3)
    ip: <ip_o_hostname_companero>
    puerto: 22
    usuario: <usuario>
    password: <password_o_vacio_si_usa_llave>
    directorio_remoto: /home/<usuario>/monit_servers_v2/colector_ubuntu/lecturas
```

Instala el servicio (mismo patrón que el colector — ver la advertencia de `StandardOutput`/`StandardError` arriba, aplica igual aquí):

```bash
nano monit_servers_v2_relay.service   # ajusta usuario/rutas/python3
sudo cp monit_servers_v2_relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable monit_servers_v2_relay
sudo systemctl start monit_servers_v2_relay
sudo systemctl status monit_servers_v2_relay
tail -f relay.log
```

Revisa `relay.log`: debe mostrar `Recolectado: <archivo>` por cada compañero con datos pendientes, y los `.csv` deben aparecer en `relay_entrante/<nombre_companero>/`.

#### Paso 3 — Configurar el inventario central (`inventario_servidores.yaml`)

**Cada compañero** necesita su propia entrada, siempre `activo: false` (nunca se conecta directo a él, ni en el caso de gateway online):

```yaml
  - nombre: <nombre_companero>
    grupo: <Cliente>/<Sitio>
    sistema_operativo: ubuntu
    activo: false
    ip:
    puerto:
    usuario:
    password:
    directorio_remoto: /home/<usuario>/monit_servers_v2/colector_ubuntu/lecturas
```

**La entrada del hub/gateway** cambia según el escenario:

- **Sitio 100% offline (hub no alcanzable)** — igual que un servidor offline normal (`activo: false`, sin credenciales). La carga es manual: trae periódicamente (USB u otro medio) tanto `colector_ubuntu/lecturas/` (lo propio del hub) como `relay/relay_entrante/<companero>/` (lo de cada compañero) a `ingesta/pendientes_offline/<nombre_correspondiente>/` en la máquina central, y dispara la ingesta (botón "Actualizar"). Para juntar todo en un solo `.zip` antes de sacarlo del sitio (en vez de copiar carpeta por carpeta), corre en el propio hub [`relay/empaquetar_offline.py`](relay/empaquetar_offline.py) — arma un `.zip` con una subcarpeta por servidor (el hub + cada compañero), verifica su integridad, y solo borra los `.csv` originales tras confirmar explícitamente. Ya de vuelta en la máquina central, deja ese `.zip` en `relay/zips/` y corre [`scripts/desempaquetar_offline.py`](scripts/desempaquetar_offline.py) — sube cada subcarpeta a DEVELOP y dispara la ingesta, sin tener que descomprimir ni copiar nada a mano.

- **Sitio con gateway online (alcanzable directo)** — `activo: true` con sus credenciales reales de SSH, más dos campos nuevos:

  ```yaml
    - nombre: <nombre_gateway>
      grupo: <Cliente>/<Sitio>
      sistema_operativo: ubuntu
      activo: true
      ip: <ip_real>
      puerto: 22
      usuario: <usuario>
      password: <password>
      directorio_remoto: /home/<usuario>/monit_servers_v2/colector_ubuntu/lecturas
      directorio_relay: /home/<usuario>/monit_servers_v2/relay/relay_entrante
      es_gateway_de: [<companero_1>, <companero_2>]
  ```

  Con esto, la ingesta (`recolectar_relay_gateway()` en `ingesta/ingesta.py`) baja sola por SFTP lo que el relay dejó en `directorio_relay/<companero>/` y lo carga a Postgres en la misma pasada — no hace falta copiar nada a mano.

### Colector Windows

En pausa — ver [ROADMAP.md](ROADMAP.md), paso 4.

### Backend + Dashboard + Ingesta (Docker — método actual, desde el 2026-10-11)

Postgres, backend/dashboard e ingesta corren en contenedores (`docker/`), con un cuarto servicio
(Ofelia) que dispara la ingesta sola cada hora. Es el método real en producción hoy (DEVELOP);
reemplaza al método manual con `pipenv`/NSSM que queda documentado más abajo como referencia
histórica, por si hiciera falta correr el backend fuera de Docker en algún escenario puntual.

#### Requisitos previos (Docker)

- Docker Engine + el plugin `docker compose` instalados en el servidor destino.
- El usuario que va a correr los contenedores debe pertenecer al grupo `docker` del sistema
  (`sudo usermod -aG docker <usuario>`, cerrar sesión y volver a entrar).

#### Paso 1 — Clonar el repositorio

```bash
git clone https://github.com/imedina27/monit_servers.git
cd monit_servers
```

#### Paso 2 — Configurar credenciales (`docker/.env`)

```bash
cp docker/.env.example docker/.env
```

Completa, además de `DB_NAME`/`DB_USER`/`DB_PASSWORD`:

- `HOST_UID`/`HOST_GID`: el uid:gid real (`id <usuario>`) del usuario que va a correr los
  contenedores en **este** servidor. Si no coincide exacto, el contenedor no puede leer
  `inventario_servidores.yaml` ni el resto de archivos montados (permission denied), aunque el
  build haya salido bien — no es universal asumir 1000 (el de `quantum` en la mayoría de los
  servidores Quantum), una cuenta personal puede tener otro uid asignado por el sistema.
- `BIND_IP` (opcional): una IP real de este host (ej. la de ZeroTier) para publicar el dashboard
  más allá de `127.0.0.1` y que el resto del equipo lo vea. Nunca `0.0.0.0` — ver la nota de
  seguridad en [`docker/CONVENCIONES_QUANTUM.md`](docker/CONVENCIONES_QUANTUM.md) sobre por qué
  `ufw`/`iptables` no filtra puertos publicados por Docker.

#### Paso 3 — Configurar el inventario de servidores

```bash
cp inventario_servidores.yaml.example inventario_servidores.yaml
chmod 600 inventario_servidores.yaml
```

Completa ahí los servidores reales (ver paso 5 de la instalación del colector Ubuntu, arriba). El campo `grupo` (ej. `Quantum` o `AbInBev/Zacatecas`) define dónde aparece cada servidor en el árbol del dashboard — la ingesta crea los niveles que falten automáticamente. `chmod 600` porque trae contraseñas reales de los servidores monitoreados.

#### Paso 4 — Levantar Postgres

```bash
cd docker
docker compose up -d postgres
```

Aplica [`db/schema.sql`](db/schema.sql) solo la primera vez (cuando el volumen `pgdata` se crea vacío). Si ya existen datos que migrar, restaura un backup aquí:

```bash
docker compose exec -T postgres psql -U <usuario> -d <nombre_db> < respaldo.sql
```

#### Paso 5 — Construir y levantar el backend

```bash
docker compose up -d --build backend
```

Abre `http://<IP_publicada>:8000/` en el navegador (o `http://127.0.0.1:8000/` si no configuraste `BIND_IP`) — ahí mismo se sirve el dashboard.

#### Ingesta periódica automática (Ofelia)

Ya viene integrada en el mismo `docker compose up` — un tercer servicio (`ofelia`, ver
`docker-compose.yml`) dispara `POST /api/ingesta/ejecutar` dentro del contenedor `backend` cada
hora en punto, leyendo labels del propio servicio. No toca el systemd del host; no hace falta
configurar nada aparte.

#### (Opcional) Umbrales del semáforo y hardware

Los umbrales de temperatura (verde/ámbar/rojo) y el hardware (chasis + garantia, CPU/GPU, RAM total + DIMMs, discos, RAID, solo informativo para el dashboard) viven en Postgres, no en archivos — ver "Administrar un servidor" más abajo. Un servidor sin umbral propio usa el default genérico (`UMBRALES_DEFAULT` en `backend/main.py`); un servidor sin hardware cargado simplemente no muestra esa info en el dashboard.

El dashboard también muestra el **uso de disco** por punto de montaje (ej. `/`, `/home`), agrupado por volumen/disco físico, con el mismo semáforo verde/ámbar/rojo (`UMBRAL_DISCO` en `backend/main.py`, 70%/90%, igual para todos los servidores). El colector lo lee de `/proc/mounts` (filtrando `tmpfs`/`overlay`/etc. con una lista blanca de sistemas de archivos reales) y lo guarda en un archivo `disco_<fecha>.csv` aparte de `lecturas_<fecha>.csv` — la ingesta distingue el tipo de archivo por su nombre y carga a la tabla `uso_disco` (serie de tiempo, hasta 1 año). El dashboard trae un **slider de fecha** debajo de las barras para navegar ese histórico — reutiliza los mismos chips "Por hora/día/mes" que ya controlan la gráfica de temperatura, un solo control para las dos cosas.

#### Carga offline desde otra máquina

Si necesitas subir un bundle offline sin entrar por SSH al servidor donde corre Docker, usa
[`scripts/cargar_offline_remoto.py`](scripts/cargar_offline_remoto.py) — sube los `.csv` por SFTP
y dispara la ingesta en un solo paso (variables `DEVELOP_*` en `.env.example`).

> Para el paso a paso completo de un despliegue real (incluyendo los bugs encontrados al correr
> contra un host compartido con otros productos) ver
> [`docker/DEVELOP_DESPLIEGUE.md`](docker/DEVELOP_DESPLIEGUE.md) y
> [`docker/CONVENCIONES_QUANTUM.md`](docker/CONVENCIONES_QUANTUM.md).

### Backend + Dashboard — método histórico (sin Docker, descontinuado)

> Ya no se usa en producción (reemplazado por Docker arriba) — queda documentado por si hace
> falta correr el backend directo en una máquina sin Docker.

#### Requisitos previos

- Python 3.14 y `pipenv` instalados.
- PostgreSQL ya instalado y accesible desde esta máquina.

#### Paso 1 — Instalar dependencias

```bash
pipenv install
```

#### Paso 2 — Configurar credenciales (`.env`)

```bash
copy .env.example .env
```

Edita `.env` con los datos reales de tu Postgres:

```ini
DB_HOST=localhost
DB_PORT=5432
DB_NAME=monit_srv
DB_USER=tu_usuario
DB_PASSWORD=tu_password
```

#### Paso 3 — Crear la base de datos y aplicar el esquema

Crea manualmente la base (ej. `monit_srv`) con tu herramienta de Postgres de preferencia (`psql`, pgAdmin, etc.), y aplica [`db/schema.sql`](db/schema.sql):

```bash
psql -h localhost -U tu_usuario -d monit_srv -f db/schema.sql
```

#### Paso 4 — Configurar el inventario de servidores

```bash
copy inventario_servidores.yaml.example inventario_servidores.yaml
```

Completa ahí los servidores reales (ver paso 5 de la instalación del colector Ubuntu, arriba).

#### Paso 5 — Levantar el servidor

```bash
pipenv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Abre `http://127.0.0.1:8000/` en el navegador — ahí mismo se sirve el dashboard (el backend expone la API en `/api/*` y el dashboard en `/`).

> El dashboard muestra lo que ya esté cargado en la base de datos. Para que haya datos, corre la ingesta (ver "Uso" abajo) después de que los colectores lleven al menos una lectura.

## Uso

### Backend (Docker)

Desde el 2026-10-11, `postgres` + `backend` + `ofelia` corren como servicios de Docker Compose
(`docker/docker-compose.yml`), con `restart: always` — vuelven solos si el host se reinicia o si
un contenedor falla. Comandos útiles, parados en `docker/`:

```bash
docker compose ps                        # estado de los 3 servicios
docker compose logs backend --tail 50    # logs del backend (tracebacks, requests)
docker compose logs ofelia                # confirmar que la ingesta automatica disparo bien
docker compose up -d --build backend     # reconstruir y reiniciar tras actualizar codigo
docker compose restart backend           # reiniciar sin reconstruir
docker compose down && docker compose up -d   # reinicio completo del stack (los datos de
                                               # Postgres persisten en el volumen "pgdata")
```

El botón "Actualizar" del dashboard (`POST /api/ingesta/ejecutar`) sigue funcionando igual que
antes, además del disparo automático cada hora de Ofelia.

#### Histórico: servicio de Windows con NSSM (descontinuado)

> Hasta el 2026-10-11 el backend corrió como servicio de Windows (`MonitServersV2_Backend`,
> instalado con [NSSM](https://nssm.cc/)) en la máquina del usuario. Se dio de baja (`sc.exe
> delete`) al migrar a Docker en DEVELOP — queda esta nota solo como referencia histórica, no
> como instrucción de instalación vigente.

### Ingesta

Corre de tres formas:

1. **Automática cada hora** — el servicio `ofelia` del `docker-compose.yml` dispara
   `POST /api/ingesta/ejecutar` dentro del contenedor `backend`, sin tocar systemd/cron del host.
   Ya viene integrado con `docker compose up -d`, no hace falta configurar nada aparte. Verificar
   con `docker compose logs ofelia`.
2. **Bajo demanda** — botón "Actualizar" en el dashboard (llama al mismo endpoint, y refresca la
   página al terminar), o `scripts/cargar_offline_remoto.py` desde otra máquina (ver "Instalación").
3. **Manual**, para cuando quieras correrla fuera de las otras dos:

   ```bash
   docker compose exec backend python ingesta/ingesta.py   # dentro de Docker
   pipenv run python ingesta/ingesta.py                     # metodo historico sin Docker
   ```

Revisa `ingesta/ingesta.log` (dentro del contenedor, o `docker compose logs backend`) para ver qué se cargó.

> **Histórico**: antes de Docker, la ingesta corría también vía tarea programada de Windows
> (`MonitServersV2_Ingesta`) — se deshabilitó el 2026-10-11 al migrar a Ofelia, y el script que la
> instalaba (`scripts/instalar_tarea_ingesta.ps1`) se eliminó por no tener ya ningún uso.

### Migrar datos históricos del proyecto viejo (CSV ancho → formato largo)

Si tienes CSVs descargados con el esquema viejo (`Monit_Servers/windows/descargar_csv.py`, columnas `cpu_*`/`gpu_*`), puedes importarlos a la base nueva:

```bash
pipenv run python db/migrar_historico_csv.py "C:\ruta\a\la\carpeta\CSV"
```

Un archivo por servidor (`DEVELOP.csv`, `MINI_LENOVO.csv`, etc., el nombre del archivo debe coincidir con el nombre del servidor). Convierte cada columna a formato largo y la inserta con `ON CONFLICT DO NOTHING` — correrlo dos veces no duplica nada.

### Respaldo y restauración de la base de datos

Para recuperarse de un formateo de la máquina central, respalda `monit_srv` de vez en cuando (2-3 veces al mes):

```bash
pipenv run python db/respaldar.py
```

Genera `bkp/Data_Base/{nombre_bd}_{ddmmaa}.sql` (carpeta gitignored — no se sube a GitHub).

Para restaurar (sobreescribe por completo la base actual):

```bash
pipenv run python db/restaurar.py bkp/Data_Base/monit_srv_011026.sql
```

Si no indicas el archivo, te deja elegir entre los respaldos disponibles en `bkp/Data_Base/`. Pide confirmación explícita antes de ejecutar, ya que reemplaza todo el contenido de la base.

### Administrar un servidor (hardware, umbrales, baja)

[`db/gestionar_servidor.py`](db/gestionar_servidor.py) es la única puerta de entrada para hardware, umbrales y baja de un servidor en Postgres. El servidor debe existir ya en la tabla `servidores` (agrégalo primero a `inventario_servidores.yaml` y corre la ingesta una vez — ver paso 5 de arriba); este script no da de alta servidores nuevos, solo administra su hardware/umbrales o lo elimina.

```bash
pipenv run python db/gestionar_servidor.py hardware DEVELOP   # chasis/CPU/GPU/RAM/discos/RAID (interactivo, Enter conserva el valor actual)
pipenv run python db/gestionar_servidor.py umbrales DEVELOP   # verde_max/ambar_max por componente (vacio = usa el default generico)
pipenv run python db/gestionar_servidor.py baja QLYMSPROD02   # elimina TODO lo del servidor en Postgres
pipenv run python db/gestionar_servidor.py importar DEVELOP.json  # carga el reporte de scripts/extraer_hardware.py, sin preguntar nada
```

Si no indicas el nombre, te deja elegir entre los servidores existentes. `baja` muestra cuántas lecturas y archivos ya ingeridos tiene antes de borrar, pide confirmación explícita (escribir `'si'`), borra en el orden correcto y limpia los grupos del árbol que queden vacíos tras el borrado (hardware/discos/RAID/umbrales se limpian solos vía `ON DELETE CASCADE`). El script **solo toca Postgres** — recuerda quitar también la entrada de `inventario_servidores.yaml` si es un retiro definitivo.

`importar` busca el servidor por hostname (sin distinguir mayúsculas/minúsculas) y solo pisa lo que el `.json` sí trae: si no se corrió como root, `dimms` viene vacío y el importador deja intacto el detalle que ya hubiera de otra fuente (no lo borra). El RAID por hardware (controlador oculta los discos) tampoco lo toca — solo refresca las filas `tipo='software'` que sí puede confirmar vía `/proc/mdstat`.

### Levantar el inventario físico de un servidor (chasis, CPU, RAM+DIMMs, discos)

[`scripts/extraer_hardware.py`](scripts/extraer_hardware.py) se corre **en el servidor Linux** (no en la máquina central) y guarda `<hostname>.json` en el directorio actual — sin instalar nada, sin tocar RAID por hardware:

```bash
sudo python3 extraer_hardware.py
```

Sin `sudo` igual corre, pero sin el detalle de DIMMs ni el número de serie del chasis (ambos requieren `dmidecode` con root) — el script avisa claramente cuando pasa esto. Copia el `.json` resultante a la máquina central y cárgalo con `gestionar_servidor.py importar` (arriba).

> El `"hostname"` que guarda el `.json` es el que reporta el propio Linux (`hostname`), que no siempre coincide con el nombre del inventario (ej. una laptop puede reportar `thinkstationpgx-07fb` en vez de `MINI_LENOVO`) — si no coinciden, `importar` no encuentra el servidor. Edita el campo `"hostname"` del `.json` al nombre real del inventario antes de importar en ese caso.

## Estructura del proyecto

```text
Monit_Servers_V2/
├── colector_ubuntu/                      ← Se instala en cada servidor Ubuntu
│   ├── monitor.py
│   ├── config.ini
│   └── monit_servers_v2.service
│
├── ingesta/                               ← Corre dentro del contenedor "backend" (Docker)
│   ├── ingesta.py
│   ├── config.ini
│   └── pendientes_offline/                ← (gitignored) archivos offline manuales, por servidor
│
├── relay/                                 ← Se instala en el servidor "hub"/gateway de un sitio offline
│   ├── relay.py
│   ├── empaquetar_offline.py              ← junta hub + companeros en un .zip, para sitios 100% offline
│   ├── config.ini
│   ├── companeros.yaml.example            ← plantilla versionada
│   ├── companeros.yaml                    ← (gitignored) credenciales reales de ese sitio
│   ├── monit_servers_v2_relay.service
│   └── relay_entrante/                    ← (gitignored) lecturas recolectadas de los companeros, por nombre
│
├── backend/                               ← API (FastAPI) + sirve el dashboard
│   ├── main.py                             ← umbrales/hardware se leen de Postgres, no de archivos
│   └── config.ini
│
├── dashboard/                             ← Pagina estatica (HTML/CSS/JS), servida por el backend
│   ├── index.html
│   └── assets/
│
├── db/
│   ├── schema.sql                          ← incluye hardware_cpu/gpu/ram, discos, raid, umbrales, uso_disco
│   ├── migrar_historico_csv.py
│   ├── respaldar.py
│   ├── restaurar.py
│   └── gestionar_servidor.py               ← hardware / umbrales / baja / importar de un servidor
│
├── bkp/Data_Base/                         ← (gitignored) respaldos .sql generados por respaldar.py
│
├── docker/                                ← Postgres + backend + ofelia (ver "Instalacion")
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   ├── .env.example                        ← plantilla versionada
│   ├── .env                                ← (gitignored) credenciales/uid/BIND_IP de este despliegue
│   ├── CONVENCIONES_QUANTUM.md             ← convenciones Docker de Quantum, de donde salio este patron
│   ├── PLAN_PRUEBA_DOCKER.md               ← prueba contra una VM, ya cerrada
│   └── DEVELOP_DESPLIEGUE.md               ← despliegue real contra DEVELOP, paso a paso
│
├── scripts/
│   ├── cargar_offline_remoto.py           ← sube un bundle offline por SFTP a un Docker remoto y dispara la ingesta
│   ├── desempaquetar_offline.py           ← sube a DEVELOP los .zip que deja relay/empaquetar_offline.py
│   └── extraer_hardware.py                ← se corre EN el servidor Linux (sudo); genera <hostname>.json
│
├── inventario_servidores.yaml.example     ← plantilla versionada
├── inventario_servidores.yaml             ← (gitignored) datos reales de los servidores
├── .env.example                           ← plantilla versionada
├── .env                                   ← (gitignored) credenciales de Postgres y de scripts/cargar_offline_remoto.py
│
├── Pipfile / Pipfile.lock
├── README.md
└── ROADMAP.md
```
