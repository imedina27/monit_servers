# Monitoreo de Temperaturas V2

Sistema centralizado para monitorear temperaturas de CPU/GPU de 15-20 servidores (Ubuntu y Windows), con base de datos PostgreSQL y dashboard web. Reemplaza el esquema anterior basado en CSV + Excel/Power Query (ver proyecto `Monit_Servers`).

## Estado

En construcción. Ver [ROADMAP.md](ROADMAP.md) para el plan de trabajo paso a paso.

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

- **Escala**: 15-20 servidores, mezcla de Ubuntu y Windows.
- **Base de datos**: PostgreSQL (ya instalado en la máquina del usuario). Se descartó SQLite por el volumen de servidores.
- **Riesgo técnico principal**: lectura de temperatura en Windows — WMI (`MSAcpi_ThermalZoneTemperature`) no es confiable en hardware moderno; se usará **LibreHardwareMonitorLib** (requiere permisos de administrador).

## Arquitectura (resumen)

- **Colectores**: un programa por SO (Ubuntu/Windows) que mide temperatura de CPU/GPU y uso de disco por punto de montaje en cada servidor.
- **Ingesta**: módulo único que descarga datos (modo online, vía scheduler, modo offline manual, o vía relay para sitios con compañeros) y los carga a Postgres — distingue temperatura de uso de disco por el nombre del archivo.
- **Backend/API**: capa que sirve agregaciones por hora/día/mes al dashboard, además del hardware/umbrales por servidor (administrados aparte, ver "Administrar un servidor").
- **Dashboard HTML**: gráfica de temperatura con zoom/desplazamiento, ficha técnica de hardware (chasis/CPU/GPU/RAM+DIMMs/discos/RAID), y uso de disco con un slider para navegar hasta 1 año de histórico.

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

- **Sitio 100% offline (hub no alcanzable)** — igual que un servidor offline normal (`activo: false`, sin credenciales). La carga es manual: trae periódicamente (USB u otro medio) tanto `colector_ubuntu/lecturas/` (lo propio del hub) como `relay/relay_entrante/<companero>/` (lo de cada compañero) a `ingesta/pendientes_offline/<nombre_correspondiente>/` en la máquina central, y dispara la ingesta (botón "Actualizar").

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

### Backend + Dashboard (en la máquina central)

#### Requisitos previos (backend + dashboard)

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

Completa ahí los servidores reales (ver paso 5 de la instalación del colector Ubuntu, arriba). El campo `grupo` (ej. `Quantum` o `AbInBev/Zacatecas`) define dónde aparece cada servidor en el árbol del dashboard — la ingesta crea los niveles que falten automáticamente.

#### Paso 5 — (Opcional) Umbrales del semáforo y hardware

Los umbrales de temperatura (verde/ámbar/rojo) y el hardware (chasis + garantia, CPU/GPU, RAM total + DIMMs, discos, RAID, solo informativo para el dashboard) viven en Postgres, no en archivos — ver "Administrar un servidor" más abajo. Un servidor sin umbral propio usa el default genérico (`UMBRALES_DEFAULT` en `backend/main.py`); un servidor sin hardware cargado simplemente no muestra esa info en el dashboard.

El dashboard también muestra el **uso de disco** por punto de montaje (ej. `/`, `/home`), agrupado por volumen/disco físico, con el mismo semáforo verde/ámbar/rojo (`UMBRAL_DISCO` en `backend/main.py`, 70%/90%, igual para todos los servidores). El colector lo lee de `/proc/mounts` (filtrando `tmpfs`/`overlay`/etc. con una lista blanca de sistemas de archivos reales) y lo guarda en un archivo `disco_<fecha>.csv` aparte de `lecturas_<fecha>.csv` — la ingesta distingue el tipo de archivo por su nombre y carga a la tabla `uso_disco` (serie de tiempo, hasta 1 año). El dashboard trae un **slider de fecha** debajo de las barras para navegar ese histórico — reutiliza los mismos chips "Por hora/día/mes" que ya controlan la gráfica de temperatura, un solo control para las dos cosas.

#### Paso 6 — Levantar el servidor

```bash
pipenv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Abre `http://127.0.0.1:8000/` en el navegador — ahí mismo se sirve el dashboard (el backend expone la API en `/api/*` y el dashboard en `/`).

> El dashboard muestra lo que ya esté cargado en la base de datos. Para que haya datos, corre la ingesta (ver "Uso" abajo) después de que los colectores lleven al menos una lectura.

## Uso

### Backend (servicio de Windows)

El backend corre como servicio de Windows (`MonitServersV2_Backend`, instalado con [NSSM](https://nssm.cc/)) — arranca solo con la máquina, se reinicia solo si falla.

#### Instalación (una sola vez, PowerShell como Administrador)

1. Descarga [NSSM](https://nssm.cc/download) y copia `win64\nssm.exe` a `%LOCALAPPDATA%\Programs\nssm\nssm.exe`.
2. Parado en la carpeta raíz del proyecto, corre:

```powershell
$nssm = "$env:LOCALAPPDATA\Programs\nssm\nssm.exe"
$servicio = "MonitServersV2_Backend"
$proyecto = (Get-Location).Path
$venvDir = Get-ChildItem -Path "$env:USERPROFILE\.virtualenvs" -Directory -Filter "Monit_Servers_V2-*" | Select-Object -First 1
$python = Join-Path $venvDir.FullName "Scripts\python.exe"

& $nssm install $servicio $python
& $nssm set $servicio AppParameters "-m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
& $nssm set $servicio AppDirectory $proyecto
& $nssm set $servicio AppStdout "$proyecto\backend\service.log"
& $nssm set $servicio AppStderr "$proyecto\backend\service.log"
& $nssm set $servicio Start SERVICE_AUTO_START
& $nssm set $servicio AppRestartDelay 5000
& $nssm start $servicio
& $nssm status $servicio
```

Debería terminar con `SERVICE_RUNNING`.

#### Comandos útiles (PowerShell como Administrador)

```powershell
Get-Service -Name "MonitServersV2_Backend"
Restart-Service -Name "MonitServersV2_Backend"   # despues de actualizar backend/*.py
```

Logs en `backend/service.log`.

### Ingesta

Corre de tres formas:

1. **Automática al iniciar sesión** — tarea programada de Windows (`MonitServersV2_Ingesta`, disparador "al iniciar sesión"). Para crearla (o recrearla si cambió algo), PowerShell como Administrador:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\instalar_tarea_ingesta.ps1
   ```

   El script ([`scripts/instalar_tarea_ingesta.ps1`](scripts/instalar_tarea_ingesta.ps1)) detecta solo la ruta del virtualenv — no hay que editar rutas a mano. Es seguro volver a correrlo: si la tarea ya existe, la reemplaza.

2. **Bajo demanda** — botón "Actualizar" en el dashboard (llama a `POST /api/ingesta/ejecutar`, que corre la ingesta en el mismo proceso del backend y refresca la página al terminar).

3. **Manual** (ver abajo), para cuando quieras correrla fuera de las otras dos.

También se puede correr manualmente en cualquier momento:

```bash
pipenv run python ingesta/ingesta.py
```

Revisa `ingesta/ingesta.log` para ver qué se cargó.

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
├── ingesta/                               ← Corre en la maquina central (Windows)
│   ├── ingesta.py
│   ├── config.ini
│   └── pendientes_offline/                ← (gitignored) archivos offline manuales, por servidor
│
├── relay/                                 ← Se instala en el servidor "hub"/gateway de un sitio offline
│   ├── relay.py
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
├── scripts/
│   ├── instalar_tarea_ingesta.ps1         ← crea la tarea programada de la ingesta
│   └── extraer_hardware.py                ← se corre EN el servidor Linux (sudo); genera <hostname>.json
│
├── inventario_servidores.yaml.example     ← plantilla versionada
├── inventario_servidores.yaml             ← (gitignored) datos reales de los servidores
├── .env.example                           ← plantilla versionada
├── .env                                   ← (gitignored) credenciales de Postgres
│
├── Pipfile / Pipfile.lock
├── README.md
└── ROADMAP.md
```
