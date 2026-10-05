# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado: [SemVer](https://semver.org/lang/es/) (`vMAJOR.MINOR.PATCH`).

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
- Script `db/eliminar_servidor.py` para dar de baja un servidor del inventario
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
