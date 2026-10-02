# Monitoreo de Temperaturas V2

Sistema centralizado para monitorear temperaturas de CPU/GPU de 15-20 servidores (Ubuntu y Windows), con base de datos PostgreSQL, dashboard web y widget de Rainmeter. Reemplaza el esquema anterior basado en CSV + Excel/Power Query (ver proyecto `Monit_Servers`).

## Estado

En construcción. Ver [ROADMAP.md](ROADMAP.md) para el plan de trabajo paso a paso.

## Contexto / decisiones ya tomadas

- **Escala**: 15-20 servidores, mezcla de Ubuntu y Windows.
- **Base de datos**: PostgreSQL (ya instalado en la máquina del usuario). Se descartó SQLite por el volumen de servidores.
- **Riesgo técnico principal**: lectura de temperatura en Windows — WMI (`MSAcpi_ThermalZoneTemperature`) no es confiable en hardware moderno; se usará **LibreHardwareMonitorLib** (requiere permisos de administrador).

## Arquitectura (resumen)

- **Colectores**: un programa por SO (Ubuntu/Windows) que mide temperatura de CPU/GPU en cada servidor.
- **Ingesta**: módulo único que descarga datos (modo online, vía scheduler) o procesa archivos entregados manualmente (modo offline), y los carga a Postgres.
- **Backend/API**: capa compartida que sirve agregaciones por hora/día/mes tanto al dashboard como al widget de Rainmeter.
- **Dashboard HTML**: visualización de variaciones de temperatura por hora/día/mes.
- **Widget de Rainmeter**: temperatura por hora de 2-3 servidores seleccionados, con indicador tipo semáforo (verde/ámbar/rojo).

## Instalación

### Colector Ubuntu (en cada servidor)

#### Requisitos previos

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

Comandos útiles:

```bash
sudo systemctl start|stop|restart|status monit_servers_v2
journalctl -u monit_servers_v2 -f
```

#### Paso 5 — Agregar el servidor al inventario central

En la máquina donde corre la ingesta (ver [`ingesta/`](ingesta/)), agrega el servidor a `inventario_servidores.yaml` (copiar de [`inventario_servidores.yaml.example`](inventario_servidores.yaml.example) si aún no existe), con un `directorio_remoto` idéntico al `directorio_salida` del paso 2. Sin este paso la ingesta no sabe que el servidor existe y no va a descargar nada de él.

### Colector Windows

En pausa — ver [ROADMAP.md](ROADMAP.md), paso 4.

### Backend + Dashboard (en la máquina central)

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

Completa ahí los servidores reales (ver paso 5 de la instalación del colector Ubuntu, arriba). El campo `grupo` (ej. `Quantum` o `AbInBev/Zacatecas`) define dónde aparece cada servidor en el árbol del dashboard — la ingesta crea los niveles que falten automáticamente.

#### Paso 5 — (Opcional) Ajustar los umbrales del semáforo

Edita [`backend/umbrales.yaml`](backend/umbrales.yaml) si los valores provisionales de temperatura (verde/ámbar/rojo) no son los que necesitas.

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
├── backend/                               ← API (FastAPI) + sirve el dashboard
│   ├── main.py
│   ├── umbrales.yaml                      ← umbrales del semaforo (verde/ambar/rojo)
│   └── config.ini
│
├── dashboard/                             ← Pagina estatica (HTML/CSS/JS), servida por el backend
│   ├── index.html
│   └── assets/
│
├── db/
│   ├── schema.sql
│   ├── migrar_historico_csv.py
│   ├── respaldar.py
│   └── restaurar.py
│
├── bkp/Data_Base/                         ← (gitignored) respaldos .sql generados por respaldar.py
│
├── scripts/
│   └── instalar_tarea_ingesta.ps1         ← crea la tarea programada de la ingesta
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
