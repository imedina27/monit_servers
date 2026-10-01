# Roadmap — Monitoreo de Temperaturas V2

> Plan de trabajo paso a paso para el proyecto nuevo. Se actualiza a medida que se completan etapas o cambian decisiones.

## 1. Revisar colector Ubuntu existente

- Evaluar `Monit_Servers/servidor/monitor.py`: ¿la detección de `lm-sensors`/`thermal_zones` (CPU) y `nvidia-smi` (GPU) sigue siendo confiable?
- Decidir si se reutiliza tal cual, se adapta, o se reescribe para alinearlo con el formato de datos que defina el esquema de BD (paso 2).

### Decisiones tomadas

1. **Formato de datos**: el colector escribe en formato "largo" (timestamp, sensor, tipo, valor) en vez del CSV ancho actual — mapea 1:1 con la tabla de lecturas en Postgres, sin transformación en la ingesta.
2. **Estrategia de archivo**: un archivo por intervalo/lote (nombre con timestamp). Tras confirmar la carga en Postgres, el módulo de ingesta borra el archivo completo — evita el riesgo de truncar un archivo que el colector sigue escribiendo.
3. **Identidad del servidor**: viene solo del inventario central (como hoy); el colector no necesita incluir su propio id.
4. **Credenciales SSH**: se mantiene usuario/password (cuenta compartida `quantum` entre varios servidores y personas). `inventario_servidores.yaml` va a `.gitignore`; se sube `inventario_servidores.yaml.example` como plantilla. Llaves SSH quedan como mejora de seguridad opcional a futuro (no bloquea nada ahora — ver "Pendiente de decidir").
5. **Modo de ejecución**: proceso persistente vía systemd (igual que hoy), con reinicio automático si falla.
6. **Intervalo de monitoreo**: variable por servidor — cada servidor mantiene su propio `config.ini` local con `intervalo_minutos`, independiente del inventario central.

### Implementado ✅

Colector actualizado en [`colector_ubuntu/`](colector_ubuntu/): `monitor.py`, `config.ini`, `monit_servers_v2.service`. Mismo motor de detección (lm-sensors/thermal_zones/nvidia-smi) que el proyecto viejo; cambia el guardado (formato largo, un archivo por lectura, timestamps en UTC) y la config (`directorio_salida` en vez de `ruta_csv`). El `.service` se renombró a `monit_servers_v2.service` (distinto al `monit_servers.service` del proyecto viejo) para no sobreescribir el servicio viejo si se copia a `/etc/systemd/system/` en el mismo servidor.

### Probado ✅ (VM Ubuntu de prueba, 192.168.220.131)

- La VM no expone sensores reales (`sensors-detect` no encontró chips, sin `thermal_zone*`, sin GPU) — limitación de la virtualización anidada, no del script.
- **Bug encontrado y corregido** (heredado del proyecto viejo): `detectar_metodo_cpu()` daba por válido "thermal_zones" con que `/sys/class/thermal` tuviera *cualquier* contenido (ej. `cooling_device*`), en vez de verificar que existieran carpetas `thermal_zone*` reales. Esto hacía que, en un equipo sin thermal zones de verdad, el script corriera indefinidamente registrando "no se obtuvieron temperaturas" en vez de abortar con un mensaje claro. Corregido para exigir `thermal_zone*` específicamente.
- Verificado en la VM: con el fix, el script ahora aborta correctamente con `"No se encontro ningun metodo de lectura de temperatura. Abortando."` cuando no hay sensores.
- Verificado localmente con datos sintéticos de `sensors`/`nvidia-smi`: `guardar_lote` escribe el archivo con las columnas correctas (`medido_en,componente,sensor,temperatura_c`) y nombres de sensor sanitizados (sin espacios), consistente con el esquema de BD del paso 2.
- **Validado con temperaturas reales** en el servidor DEVELOP (192.168.192.205): detectó `lm-sensors` (11 sensores de CPU) y 2 GPUs NVIDIA vía `nvidia-smi`, generó un archivo por lectura con datos reales y formato correcto, sin interferir con el servicio viejo (`monit_servers`) que sigue activo en ese mismo servidor. Prueba corrida en `check/monit_servers_v2_test/` (carpeta de prueba, se deja ahí).

**Paso 1 cerrado.**

## 2. Definir esquema de base de datos (PostgreSQL)

- Modelo de datos: servidores, lecturas de temperatura (CPU/GPU, timestamp, origen online/offline), estado de carga.
- Debe quedar definido antes de tocar los colectores o el módulo de ingesta, para que ambos escriban/lean en el mismo formato desde el inicio.

## 3. Inventario y configuración de servidores

- Lista central de los 15-20 servidores: hostname/IP, SO (Ubuntu/Windows), método de acceso (SSH, WinRM, API local, etc.) y credenciales.
- Es la base que usará el modo "online" para saber a qué servidores conectarse.

### Implementado ✅

- [`inventario_servidores.yaml.example`](inventario_servidores.yaml.example): plantilla versionada en Git.
- `inventario_servidores.yaml`: archivo real (gitignored) con los 2 servidores conocidos (DEVELOP, MINI_LENOVO), migrados del proyecto viejo.
- [`.gitignore`](.gitignore): excluye el inventario real, `.env`, logs y la carpeta `lecturas/` generada por el colector.
- Cada servidor tiene `nombre`, `sistema_operativo`, `activo`, `ip`, `puerto`, `usuario`, `password` y `directorio_remoto` (debe coincidir con el `directorio_salida` del `config.ini` del colector en ese servidor — el módulo de ingesta, paso 5, listará y descargará archivos de ahí).
- No incluye `intervalo_minutos` — eso vive en el `config.ini` local de cada servidor (decisión ya tomada en el paso 1).

## 4. Crear el colector de Windows ⏸ EN PAUSA

- Validar primero la lectura de temperatura con **LibreHardwareMonitorLib** (requiere permisos de administrador) — mayor riesgo técnico del proyecto.
- Construir el colector equivalente al de Ubuntu (CPU/GPU), alineado al esquema del paso 2.

**Decisión (2026-10-01)**: se pospone. La mayoría de los servidores son Linux; el esfuerzo adicional que implica este componente no se justifica por ahora frente al resto del roadmap. El proyecto sigue adelante solo con servidores Ubuntu; este paso se retoma cuando haga falta cubrir servidores Windows.

### Investigación hecha (para no repetirla al retomar)

- **`LibreHardwareMonitorLib` sí funciona** desde Python vía `pythonnet` (wheel compatible con Python 3.14 confirmado). Se probó en la máquina del usuario:
  - Temperaturas de **GPU funcionan sin admin** (NVIDIA vía la librería, valores reales obtenidos).
  - Temperaturas de **CPU requieren privilegios de administrador** (salen `None` sin elevar) — igual que anticipaba el README original.
  - Incrustar la librería directo en Python fue incómodo: el paquete NuGet no trae todas las dependencias necesarias (`RAMSPDToolkit`, `DiskInfoToolkit`, `System.IO.Ports`, etc.); hubo que usar el ZIP de la release completa de GitHub (no el paquete NuGet) para tener todas las DLLs necesarias, y cargarlo con el runtime de .NET Framework (`pythonnet.load("netfx")`), no con .NET 8.
- **Alternativa explorada**: usar la app oficial `LibreHardwareMonitor.exe` (el usuario ya la tiene instalada) con su función **"Remote Web Server"** activada, y que el colector en Python solo haga `requests.get("http://localhost:8085/data.json")` — evita toda la complicación de interop .NET/Python.
  - Problema encontrado: el estado "activado" del Remote Web Server **no se guarda** en la configuración de la app entre reinicios (solo se persisten puerto/IP/autenticación) — se vuelve a encender manualmente cada vez que la app arranca, vía el ícono de la bandeja del sistema. Esto lo hace poco confiable para monitoreo desatendido tal cual, salvo que se resuelva ese punto (ej. revisar si existe alguna forma de auto-activarlo, o si una versión distinta/config distinta lo permite).
- **Alternativas descartadas**: WMI (`MSAcpi_ThermalZoneTemperature`, poco confiable en hardware moderno — motivo original de excluirlo), OpenHardwareMonitor (predecesor sin mantenimiento, LibreHardwareMonitorLib es su fork activo), HWiNFO (cerrado, más pesado de automatizar), herramientas de fabricante (Intel/AMD, no cubren ambos fabricantes a la vez).
- **Pendiente si se retoma**: decidir entre (a) resolver el problema de persistencia del Remote Web Server, o (b) aceptar la complejidad de incrustar la librería vía `pythonnet` con el bundle completo de dependencias, y luego definir modo de ejecución elevado (servicio/tarea programada) — mismas preguntas de diseño que se resolvieron para el colector Ubuntu (formato de datos, estrategia de archivo, identidad del servidor, intervalo) aplican igual aquí.

## 5. Módulo de descarga/ingesta de valores

Una sola función de importación hacia Postgres, con dos entradas (online vía scheduler, offline manual apuntando a archivo):

1. Descargar los valores de los servidores online.
2. Cargar estos valores a la BD.
3. Revisar si hay archivos pendientes de carga de los servidores offline.
4. Cargar esos archivos offline a la BD.
5. Borrar los valores ya cargados en los servidores online **solo tras confirmar que la escritura en Postgres fue exitosa**.
6. Borrar los valores ya cargados de los archivos offline, con la misma precaución.

- Con 15-20 servidores, paralelizar la descarga en modo online (el script actual de Windows descarga secuencial).

### Implementado ✅

Módulo en [`ingesta/`](ingesta/): `ingesta.py`, `config.ini` (sin secretos: `max_workers`, carpeta offline), y `.env.example` en la raíz (secretos de Postgres: `DB_HOST/PORT/NAME/USER/PASSWORD`).

- **Online**: por cada servidor activo del inventario (en paralelo, `ThreadPoolExecutor`, cada hilo con su propia conexión SSH y a la BD), lista los `.csv` pendientes en `directorio_remoto`, descarga cada uno directo a memoria (sin copia local intermedia), lo parsea e inserta, y solo si el `commit` fue exitoso lo borra del servidor.
- **Offline**: igual pero leyendo de `ingesta/pendientes_offline/<nombre_servidor>/` (carpeta local gitignored); el nombre de la subcarpeta debe coincidir con el `nombre` del servidor en el inventario, si no, se omite con un aviso en el log.
- **Idempotencia doble**: antes de procesar un archivo se consulta `archivos_ingeridos` (evita volver a descargar/leer algo ya cargado); además el `INSERT` en `lecturas` usa `ON CONFLICT DO NOTHING` sobre el mismo `UNIQUE` del esquema, como red de seguridad adicional.
- La tabla `servidores` se mantiene sincronizada automáticamente desde el inventario (upsert por `nombre`) en cada corrida — no hace falta darlos de alta a mano en la BD.
- Nota técnica: se usó `psycopg2-binary` en vez de `psycopg` v3 — una política de Control de Aplicaciones de Windows bloqueó la DLL binaria de `psycopg` v3 en esta máquina.

### Probado ✅ (end-to-end contra DEVELOP + Postgres real)

- Base de datos `monit_srv` creada en Postgres local (`qua_admin`), esquema aplicado.
- Se desplegó `colector_ubuntu/` en la ruta real de producción en DEVELOP (`/home/quantum/check/monit_servers_v2/colector_ubuntu/`, dentro del espacio ya acordado, sin tocar el servicio viejo) y se generaron 2 lecturas reales.
- `ingesta.py` las descargó, insertó 26 filas en `lecturas`, registró 2 filas en `archivos_ingeridos`, y borró los archivos del servidor tras confirmar el `commit`.
- Verificado en el servidor: la carpeta `lecturas/` quedó vacía después de la ingesta.
- Verificada la idempotencia: una segunda corrida sin archivos nuevos no insertó ni duplicó nada.
- `config.ini` remoto se dejó restaurado a `intervalo_minutos = 60` (se había bajado a 1 min solo para la prueba).
- Nota: aún no se instaló el servicio systemd en DEVELOP para este `colector_ubuntu/v2` — por ahora solo se corrió manualmente para la prueba.

## 6. Backend / API de consultas

- Capa única (FastAPI/Flask) que exponga agregaciones por hora/día/mes.
- La usan tanto el dashboard HTML como el widget de Rainmeter, evitando duplicar lógica de consulta en cada vista.
- Calcula el estado del semáforo (verde/ámbar/rojo, ver paso 9) y lo entrega ya resuelto junto a la temperatura — ni el dashboard ni el widget evalúan umbrales por su cuenta.

### Implementado y probado ✅

Backend en [`backend/`](backend/): `main.py` (FastAPI), `umbrales.yaml` (umbrales del semáforo — **valores provisionales**, ver "Pendiente de decidir"), `config.ini` (host/puerto, por defecto `127.0.0.1:8000`, solo accesible desde esta máquina).

Endpoints, probados contra los datos reales ya cargados de DEVELOP:

- `GET /servidores` — catálogo de servidores.
- `GET /servidores/{nombre}/actual` — última lectura por sensor, con `estado` (verde/ámbar/rojo) ya calculado.
- `GET /servidores/{nombre}/historico?agrupacion=hora|dia|mes` — promedios agregados por sensor y periodo, para las gráficas del dashboard.
- 404 correcto para un servidor que no existe.

Se eligió **FastAPI** (sobre Flask, que el README dejaba como alternativa) por la documentación automática (`/docs`) y validación de tipos integrada. Corre con `uvicorn` — se confirmó compatible con Python 3.14.

## 7. Dashboard HTML

- Página que consume la API del paso 6 y grafica variaciones de temperatura (por hora/día/mes).
- Aplicar imagen empresarial de Quantum (colores, logo, tipografía corporativa).

### Implementado y validado visualmente ✅

Dashboard en [`dashboard/`](dashboard/), servido por el backend (`app.mount("/", StaticFiles(...))`); la API se movió a `/api/*` para no chocar con el mount.

- **Marca**: colores reales del Manual de Identidad (`#E2724B` naranja, `#040918` fondo oscuro), tipografía Libre Franklin autohospedada (`.ttf` copiados del manual, pesos Regular/Medium/SemiBold/Bold), logos con transparencia real (verificado canal alfa).
- **Tema oscuro por defecto** (combinación principal de la marca), con toggle a tema claro — mismos íconos de "gota" que ya usa `Cam_Lens_V2` para ese botón. Preferencia guardada en `localStorage`.
- **Semáforo**: mismos colores ya usados en `Cam_Lens_V2/styles/stylesheet.py` (verde `#2FA36B`, ámbar `#E0902E`, rojo `#D9534F`) — consistencia entre herramientas internas de Quantum.
- **Colores de las líneas de la gráfica** (distintos del semáforo, para no mezclar "estado" con "identidad de serie"): paleta categórica validada del skill de dataviz, saltando el slot "naranja" porque choca con el acento de marca. *Nota: no pude correr el validador (`node` no está instalado en esta máquina) — usé los valores ya validados por el skill contra sus superficies de referencia (muy cercanas a las nuestras), no una validación exacta contra `#040918`.*
- **Contenido**: tarjetas de estado actual (CPU = núcleo más caliente, no promedio — para no esconder un core sobrecalentado; una tarjeta por GPU), tabla expandible con todos los sensores, gráfica histórica con selector hora/día/mes, leyenda, tooltip al pasar el mouse. Refresco automático cada 5 minutos.
- **Probado**: arranqué el servidor y verifiqué con `curl` que el HTML, CSS, JS, fuentes, imágenes y los 3 endpoints de la API se sirven correctamente (200, content-type correcto) contra los datos reales de DEVELOP. El renderizado visual lo confirmó el usuario directamente en su navegador (no hay `Node.js`/`chromium-cli` en esta máquina para una captura automatizada propia).
- **Ajustes pedidos por el usuario tras la primera revisión**: logo del header 3x más grande, título centrado "Server Temperature Monitor", selector de servidor movido de la barra superior al encabezado de la sección "Estado actual".
- Instrucciones de instalación del backend + dashboard agregadas al [README.md](README.md) (crear `.env`, aplicar `db/schema.sql`, configurar inventario, levantar `uvicorn`).

## 8. Respaldo y restauración de la base de datos

- Scripts de línea de comandos para respaldar/restaurar `monit_srv` completa, pensados para recuperarse de un formateo de la máquina central.

### Implementado y probado ✅

- [`db/respaldar.py`](db/respaldar.py): corre `pg_dump --clean --if-exists` (credenciales desde `.env`) y guarda en `bkp/Data_Base/{DB_NAME}_{ddmmaa}.sql` (carpeta gitignored). `--clean --if-exists` hace que el archivo incluya los `DROP` necesarios, para que restaurar deje la base exactamente como el respaldo, sin conflictos.
- [`db/restaurar.py`](db/restaurar.py): acepta la ruta del archivo como argumento, o si no se da ninguno, lista los respaldos disponibles en `bkp/Data_Base/` para elegir uno interactivamente. Pide confirmación explícita (`escribe 'si'`) antes de sobreescribir — la restauración reemplaza todo el contenido de la base, a propósito. Si la base no existe (ej. máquina recién formateada), la crea antes de restaurar.
- **Probado end-to-end**: respaldo real de `monit_srv` → se vació la base a propósito (`TRUNCATE`) → restaurada desde el respaldo → conteos de filas idénticos a los originales (26 lecturas, 2 archivos_ingeridos).

## 9. Widget de Rainmeter

- Mostrar temperatura por hora de 2-3 servidores seleccionados, consumiendo la API (plugin `WebParser`).

## 10. Indicador tipo semáforo en el widget

- Junto a cada temperatura, un punto de color según rango: Verde (normal), Ámbar (advertencia), Rojo (crítico).
- El color se calcula en el backend (paso 6), no en el widget ni en el dashboard.
- **Decisión**: los umbrales viven en un archivo YAML que lee el backend (no en la BD) — más simple; cambiarlos implica editar el archivo y reiniciar el servicio.
- Falta definir los valores exactos de los umbrales por tipo de sensor (CPU/GPU).

## 11. Validación end-to-end (opcional, recomendado)

- Prueba completa del flujo: colector → ingesta → BD → dashboard/widget, con al menos un servidor Ubuntu y uno Windows reales antes de dar el proyecto por cerrado.

## Pendiente de decidir

- Valores exactos de los umbrales de temperatura para el semáforo (paso 10) — ya se decidió que viven en un YAML leído por el backend (`backend/umbrales.yaml`); los que hay ahí son provisionales (70/85°C CPU, 75/85°C GPU).
- ~~Detalles de la imagen empresarial Quantum a aplicar (paso 7).~~ Resuelto — colores, logo y tipografía reales ya aplicados en el dashboard (paso 7).
- **Ambiente conda para `colector_ubuntu`** (paso 1 / instalación): el usuario quiere que la instalación en servidores use un ambiente virtual con conda antes de todo. Pendiente: por qué `conda` no aparece en DEVELOP (`which conda` no encontró nada, ni en rutas comunes) — el usuario lo va a verificar. Una vez resuelto, falta decidir nombre del ambiente y versión de Python, y documentarlo en el README.
- **Instalar el servicio systemd real en DEVELOP**: por ahora `colector_ubuntu` solo se corrió manualmente ahí para pruebas (ver paso 5); falta copiar `monit_servers_v2.service` a `/etc/systemd/system/` y habilitarlo para que quede corriendo de forma persistente.

## Mejoras futuras (no bloquean el roadmap)

- Migrar la autenticación SSH de usuario/password a llaves públicas/privadas (más seguro; no es necesario para el objetivo actual de no subir secretos a GitHub).
