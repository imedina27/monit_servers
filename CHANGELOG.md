# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado: [SemVer](https://semver.org/lang/es/) (`vMAJOR.MINOR.PATCH`).

## [Unreleased]

### Added

- Tarjetas "Umbral CPU"/"Umbral GPU" en el dashboard (verde/ámbar/rojo configurados por
  servidor en Postgres), junto a las tarjetas de temperatura (paso 17).

### Fixed

- `/api/servidores/{nombre}/historico` y `/disco/historico` ya no agregaban TODO el
  histórico de la tabla en cada carga — en servidores con meses de datos (`DEVELOP`,
  `MINI_LENOVO`) eso tardaba 1.5-3.4s por clic en el árbol, dejando la info del servidor
  anterior congelada en pantalla mientras tanto. Ahora cada endpoint acepta `completo`
  (bool) y por defecto limita la ventana según la agrupación ("hora" 30 días, "día" 1 año,
  "mes" sin límite); el dashboard pide el resto en una sola petición de respaldo solo si
  el usuario arrastra el desplazador/slider hasta el borde más viejo ya cargado.
- Umbral de "lectura obsoleta" (el que marca `--°C` en vez del valor real) subido de 3h
  a 24h — sitios 100% offline como AbInBev se descargan ~1 vez al día, no cada hora.
- La tarjeta "CPU (máx.)" podía marcarse como obsoleta (`--°C`) por un solo sensor
  fantasma con una lectura vieja de temperatura alta, aunque el resto de los cores
  tuvieran datos recientes.
- Ciudades/plantas reales de los 7 servidores nuevos de AbInBev corregidas en el
  inventario y la documentación (no todos eran de Zacatecas).
- Orden de `QLYMSPROD03` en el inventario de AbInBev corregido — aparecía al final del
  árbol del dashboard en vez de justo después de Zacatecas.
- Al cambiar de servidor con internet lento, los datos del servidor anterior se quedaban
  congelados en pantalla varios segundos sin ninguna señal de que se estuviera cargando
  otra cosa. Ahora se atenúa el contenido y aparece "Cargando..." si la respuesta tarda
  más de 200ms (sin parpadeo en conexiones normales); de paso, una respuesta tardía de un
  servidor ya no se pinta si el usuario ya eligió otro mientras tanto (paso 19).
- El % de uso de disco del dashboard salía siempre más bajo que `df -h` en el mismo
  servidor — `df` excluye del cálculo el espacio reservado para root (~5% en ext4),
  nosotros no. Colector, ingesta y backend actualizados para calcularlo igual que `df`
  (paso 20; requiere actualizar el colector en cada servidor y migrar la base de datos,
  ver ROADMAP).

## [v2.0.0] - 2026-10-11

Migración del stack central (Postgres + backend/dashboard + ingesta) de la máquina Windows
del usuario a **DEVELOP** (Ubuntu Server), empaquetado con **Docker** — el cambio de
infraestructura más grande desde el primer release. Además: uso de disco por punto de
montaje, tercer sitio en operación (C5i/Colima), hardware/umbrales reales completados para
todos los servidores conocidos, y varios scripts nuevos para sitios offline.

### Added

- **Docker**: `docker/Dockerfile` + `docker-compose.yml` para Postgres + backend/dashboard +
  ingesta, siguiendo las convenciones de Quantum (`docker/CONVENCIONES_QUANTUM.md`): usuario
  real del host (no root), red dedicada, `host.docker.internal` vía `host-gateway`, exposición
  de puertos conservadora por defecto (`BIND_IP`, loopback-only salvo que se configure otra IP).
- **Scheduler Ofelia**: la ingesta corre sola cada hora dentro de Docker (`docker exec` vía
  labels en `docker-compose.yml`), sin tocar systemd/cron del host.
- **Uso de disco por volumen/punto de montaje** en el dashboard (paso 16): nueva tabla
  `uso_disco`, colector agnóstico de LVM, slider de fecha para navegar hasta 1 año de histórico
  reutilizando los mismos controles de agrupación de la gráfica de temperatura.
- **Sitio C5i/Colima** (`quantumdata` + `colima00/01/02`) puesto en operación real — tercer
  cliente con el mecanismo de relay/gateway, confirmado contra producción con múltiples
  compañeros de un mismo gateway.
- **`scripts/cargar_offline_remoto.py`**: sube un bundle de un servidor offline por SFTP
  directo a DEVELOP y dispara la ingesta, sin entrar por SSH a mano.
- **`relay/empaquetar_offline.py`** + **`scripts/desempaquetar_offline.py`**: empaquetan en un
  solo `.zip` los datos de un sitio 100% offline (hub + compañeros) en el propio sitio, y lo
  suben/descomprimen del lado de DEVELOP en un solo paso.
- **Usuario dedicado `imedina`** en DEVELOP (servidor compartido con otros productos de
  Quantum), con grupo primario exclusivo — a diferencia de otras cuentas del servidor que
  comparten grupo y terminan con acceso de lectura mutuo a sus homes.
- Hardware real (chasis/CPU/GPU/discos, verificado con `sudo`) y umbrales de temperatura
  investigados por modelo real, completados para los últimos servidores que quedaban
  pendientes (`QLYMSPROD01`/`QLYMSPROD02` de AbInBev, `MINI_LENOVO`).

### Changed

- **`psycopg2` → `psycopg` v3** en todo el proyecto (backend, ingesta, los 4 scripts de `db/`)
  — el bloqueo de la política de Control de Aplicaciones de Windows que motivó usar v2
  originalmente ya no aplica en esta máquina.
- El dashboard pasa de ser accesible solo en la máquina Windows del usuario a publicarse en la
  IP real de DEVELOP (`http://192.168.192.205:8000`), alcanzable por todo el equipo.

### Fixed

- `db/gestionar_servidor.py` (`cmd_baja`): no borraba `uso_disco` (tabla sin
  `ON DELETE CASCADE`, agregada después de escribirse la función) — hacía fallar la baja de un
  servidor con uso de disco cargado.
- `postgres:18` exige montar su volumen en `/var/lib/postgresql` directo, ya no en
  `/var/lib/postgresql/data` como `postgres:16` — encontrado al desplegar contra DEVELOP real.
- `uid:gid` del contenedor backend estaba hardcodeado a `1000` (el de `quantum` en todos los
  servidores conocidos hasta entonces); no generalizaba a una cuenta personal con otro uid
  asignado por el sistema — ahora configurable vía `HOST_UID`/`HOST_GID`.

### Removed

- Servicio de Windows (NSSM) y tarea programada de la ingesta — reemplazados por Docker +
  Ofelia. `scripts/instalar_tarea_ingesta.ps1` eliminado por quedar sin ningún uso.
- `TAD_18_de_Marzo` (sitio PEMEX): PoC terminada, dado de baja del inventario y la base de
  datos.

[v2.0.0]: https://github.com/imedina27/monit_servers/releases/tag/v2.0.0

## [v1.0.0] - 2026-10-04

Primer release estable: colector, base de datos, ingesta, backend/dashboard y
relay funcionando de punta a punta, con dos sitios reales en producción
(AbInBev Zacatecas y API/Manzanillo) y un tercero en curso (C5i/Colima).

### Added

- Colector Ubuntu (`colector_ubuntu/`): lee temperaturas de CPU (`lm-sensors`/
  `thermal_zones`, agnóstico de fabricante Intel/AMD) y GPU (`nvidia-smi`),
  formato largo, un archivo por lote, como servicio `systemd` persistente.
- Esquema de base de datos PostgreSQL (`db/schema.sql`) para servidores, grupos
  y lecturas.
- Módulo de ingesta (`ingesta/`): descarga online por SSH/SFTP en paralelo,
  carga offline manual por carpeta, idempotencia doble, sincronización
  automática de servidores/grupos del inventario.
- Backend API en FastAPI (`backend/`) con cálculo de semáforo (verde/ámbar/
  rojo) resuelto en el servidor.
- Dashboard web (`dashboard/`) con imagen de marca Quantum Labs, árbol de
  servidores por cliente/ubicación, gráfica histórica con zoom/desplazamiento,
  tema oscuro/claro y botón "Actualizar" (ingesta bajo demanda).
- Scripts de respaldo/restauración de la base de datos (`db/respaldar.py`,
  `db/restaurar.py`) y migración de históricos del proyecto viejo.
- Backend como servicio de Windows (NSSM) + tarea programada de ingesta al
  iniciar sesión.
- Mecanismo de relay (`relay/`) para sitios offline/semi-offline: recolección
  autónoma por SSH/SFTP desde un servidor "hub"/gateway hacia sus compañeros,
  con dos modos de carga a central — manual (sitio 100% offline, AbInBev) y
  automática vía `recolectar_relay_gateway()` (gateway online, API/Manzanillo).
- `db/gestionar_servidor.py baja` para dar de baja un servidor del inventario
  y su historial.

### Fixed

- `monitor.py`: detección de `thermal_zones` exigía carpetas reales en vez de
  cualquier contenido de `/sys/class/thermal`.
- `monitor.py`: detección de sensores de CPU dependía de etiquetas específicas
  de Intel (`Core`/`Package`); ahora detecta por sufijo de unidad (`°C`/`C`),
  agnóstico de fabricante, y desambigua chips repetidos en servidores
  multi-socket.
- `ingesta.py`: ruta de `pendientes_offline` calculada desde la raíz del
  repositorio en vez de desde `ingesta/`, hacía fallar la carga offline en
  silencio.
- `systemd`: `StandardOutput=append:`/`StandardError=append:` crea el archivo
  de log como `root` antes de bajar privilegios al usuario del servicio,
  provocando un ciclo de reinicio infinito — se removieron esas líneas de los
  `.service`, el log de aplicación ya lo maneja Python.
- `scp -r origen destino/`: si `destino/` no existe en el remoto, aplana el
  contenido en vez de anidarlo — documentado el workaround (crear el
  directorio destino primero).
- `pip3 install` en servidores con PEP 668 (`externally-managed-environment`):
  documentado el uso de `apt install python3-paramiko python3-yaml` en su
  lugar.

[v1.0.0]: https://github.com/imedina27/monit_servers/releases/tag/v1.0.0
