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

### Implementado ✅ (colector Ubuntu)

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

### Implementado ✅ (inventario)

- [`inventario_servidores.yaml.example`](inventario_servidores.yaml.example): plantilla versionada en Git.
- `inventario_servidores.yaml`: archivo real (gitignored) con los 2 servidores conocidos (DEVELOP, MINI_LENOVO), migrados del proyecto viejo.
- [`.gitignore`](.gitignore): excluye el inventario real, `.env`, logs y la carpeta `lecturas/` generada por el colector.
- Cada servidor tiene `nombre`, `sistema_operativo`, `activo`, `ip`, `puerto`, `usuario`, `password` y `directorio_remoto` (debe coincidir con el `directorio_salida` del `config.ini` del colector en ese servidor — el módulo de ingesta, paso 5, listará y descargará archivos de ahí).
- No incluye `intervalo_minutos` — eso vive en el `config.ini` local de cada servidor (decisión ya tomada en el paso 1).
- **`activo` es la bandera de online/offline** (decisión 2026-10-02): `true` = la ingesta se conecta por SSH automáticamente; `false` = sin alcance directo desde la máquina central, carga manual vía `pendientes_offline/<nombre>/` (paso 11). Cuando `activo: false`, `ip`/`puerto`/`usuario`/`password` quedan vacíos (no aplican); `directorio_remoto` se conserva como documentación de dónde escribe el colector en ese equipo. Los servidores ilustrativos de ejemplo (QLYMSPROD02-04, solo para ver el árbol con varios niveles) se quitaron del inventario real; `QLYMSPROD01` ya quedó como entrada real offline (ver paso 11).

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

### Implementado ✅ (ingesta)

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

### Implementado y probado ✅ (backend)

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

### Extra: árbol de servidores por cliente/ubicación ✅

El combo plano de servidores se iba a volver inmanejable con 15-20+ servidores de varios clientes. Se reemplazó por una barra lateral con árbol expandible/colapsable:

- **Esquema**: tabla `grupos` auto-referenciada (`grupo_padre_id`), profundidad libre; `servidores.grupo_id` apunta a la hoja del árbol de la que cuelga cada servidor.
- **Configuración**: campo `grupo` en `inventario_servidores.yaml`, como ruta tipo carpeta (`Quantum` o `AbInBev/Zacatecas`) — la ingesta crea los niveles que falten automáticamente, nada se da de alta a mano en la BD.
- **`ingesta.py`**: ahora sincroniza metadatos (servidor + grupo) de **todos** los servidores del inventario en cada corrida, no solo los activos — así un servidor `activo: false` (de alta futura, sin credenciales reales todavía) igual aparece en el árbol, aunque no se le descargue nada.
- **Backend**: `GET /api/grupos` arma el árbol completo (grupos anidados + servidores como hojas) en una sola llamada.
- **Dashboard**: el combo se quitó por completo; una barra lateral dibuja el árbol (expandido por defecto), con clic para expandir/colapsar grupos y para seleccionar un servidor.
- Se agregaron servidores ilustrativos (`AbInBev/Zacatecas/Apan/Medellin`, `activo: false`, IPs falsas) al inventario real para poder ver el árbol con varios niveles — reemplazar por servidores reales cuando existan.

**Ajustes pedidos tras la primera revisión:**

- Árbol movido al lado **derecho** de la pantalla (no izquierdo).
- **Orden real del YAML, no alfabético**: se agregó columna `orden` a `grupos` y `servidores`; `ingesta.py` la recalcula en cada corrida a partir de la posición de cada servidor en el inventario (un grupo repetido conserva el orden de su primera aparición). Backend y dashboard ordenan por esa columna.

### Extra: zoom y desplazamiento en la gráfica histórica ✅

El histórico completo (hasta 7 meses) se amontonaba en una sola vista. Ahora la gráfica muestra una ventana acotada por defecto, con zoom (rueda del mouse) y desplazamiento (barra bajo la gráfica):

- **Ventana por defecto, anclada al dato más reciente disponible** (no al reloj — así no se ve "vacía" si el colector no ha mandado nada recientemente): 48h en "por hora", 7 días en "por día", 4 meses en "por mes".
- **Zoom con scroll**: rueda hacia arriba = acerca (ventana más chica); hacia abajo = aleja (ventana más grande), hasta el límite de datos disponibles. El extremo derecho de la ventana se queda fijo al hacer zoom (no salta a "ahora").
- **Barra de desplazamiento** bajo la gráfica (arrastrar, o clic para saltar) para navegar a periodos anteriores una vez hecho zoom. Se oculta sola cuando la ventana ya muestra todo el histórico disponible.
- **Límites de zoom configurables**: bloque `CONFIG_ZOOM` al inicio de `dashboard/assets/js/app.js` (ventana por defecto, mínimo de zoom-in, tamaño del paso por "tick" de scroll, por cada agrupación).
- Todo es client-side: el historico completo se trae una sola vez del backend; el zoom/desplazamiento solo recorta y reescala en el navegador, sin pegarle de nuevo a la API.
- El refresco automático (cada 5 min) y el cambio de tema ya no resetean el zoom/desplazamiento del usuario.

## 8. Respaldo y restauración de la base de datos

- Scripts de línea de comandos para respaldar/restaurar `monit_srv` completa, pensados para recuperarse de un formateo de la máquina central.

### Implementado y probado ✅ (respaldo/restauración)

- [`db/respaldar.py`](db/respaldar.py): corre `pg_dump --clean --if-exists` (credenciales desde `.env`) y guarda en `bkp/Data_Base/{DB_NAME}_{ddmmaa}.sql` (carpeta gitignored). `--clean --if-exists` hace que el archivo incluya los `DROP` necesarios, para que restaurar deje la base exactamente como el respaldo, sin conflictos.
- [`db/restaurar.py`](db/restaurar.py): acepta la ruta del archivo como argumento, o si no se da ninguno, lista los respaldos disponibles en `bkp/Data_Base/` para elegir uno interactivamente. Pide confirmación explícita (`escribe 'si'`) antes de sobreescribir — la restauración reemplaza todo el contenido de la base, a propósito. Si la base no existe (ej. máquina recién formateada), la crea antes de restaurar.
- **Probado end-to-end**: respaldo real de `monit_srv` → se vació la base a propósito (`TRUNCATE`) → restaurada desde el respaldo → conteos de filas idénticos a los originales (26 lecturas, 2 archivos_ingeridos).

### Extra: migración de históricos del proyecto viejo ✅

Se agregó [`db/migrar_historico_csv.py`](db/migrar_historico_csv.py) para convertir los CSV anchos del proyecto viejo (`cpu_*`/`gpu_*`) al formato largo e insertarlos en `lecturas`. Se usó para importar el histórico real de DEVELOP y MINI_LENOVO (marzo–octubre 2026, ~98,000 lecturas) — el dashboard ya tiene 7 meses de datos reales para probar agrupación por día/mes, no solo por hora.

### Extra: despliegue persistente (servicio + tarea programada + botón) ✅

El dashboard ya no depende de que haya una terminal abierta corriendo `uvicorn` a mano:

- **Backend como servicio de Windows**: instalado con [NSSM](https://nssm.cc/) (`MonitServersV2_Backend`) — arranque automático, se reinicia solo si falla. NSSM **no fue bloqueado** por la política de Control de Aplicaciones de esta máquina (sí lo había sido `psycopg` v3 antes), así que funcionó sin rodeos.
- **Ingesta al iniciar sesión**: tarea programada de Windows (`MonitServersV2_Ingesta`, disparador "al iniciar sesión"), corre una sola vez por sesión — decisión explícita del usuario de no tenerla recurrente, para no pegarle a los servidores sin necesidad.
- **Botón "Actualizar" en el dashboard**: dispara la ingesta bajo demanda (`POST /api/ingesta/ejecutar`, corre `ingesta.main()` en el mismo proceso del backend) y refresca árbol + estado actual + histórico al terminar, sin perder la selección de servidor ni el zoom de la gráfica.
- Instalar el servicio/tarea requiere PowerShell como Administrador (comandos documentados en el README) — no se puede hacer sin elevación.

## 9. Instalar el servicio systemd real del colector en los servidores de Quantum

- **Contexto**: `colector_ubuntu` (paso 1) solo se ha corrido manualmente en DEVELOP para pruebas (ver paso 5); falta copiar `monit_servers_v2.service` a `/etc/systemd/system/` y habilitarlo ahí y en MINI_LENOVO, para que quede corriendo de forma persistente (reinicio automático si falla, arranque solo).
- No depende de nada más del roadmap — el colector es independiente de dónde viva el backend, se puede hacer ya.
- Nota: si para entonces ya se resolvió el tema del ambiente conda (ver "Pendiente de decidir"), el `.service` debe apuntar al intérprete de ese ambiente en vez del venv actual.

### Implementado y probado ✅ (servicio systemd)

- Servicio viejo (`monit_servers.service`) dado de baja correctamente en DEVELOP antes de instalar el nuevo: `stop` → `disable` → borrar unit file → `daemon-reload` → `reset-failed`. Se respaldó su directorio completo (`tar.gz` en el home de `quantum`) antes de borrarlo, una vez confirmado que su histórico ya estaba migrado a Postgres (ver paso 8).
- `monit_servers_v2.service` instalado y habilitado (`enable` + `start`) en **DEVELOP** y en **MINI_LENOVO** — ambos `active (running)`, generando lotes cada hora sin interferir entre sí ni con otros procesos del servidor.
- **Bug encontrado y corregido (en ambos servidores)**: `monitor.log` quedó con dueño `root` (de una ejecución manual anterior con `sudo`), y el servicio corre como `User=quantum` — provocaba `PermissionError` en `logging.basicConfig()` y un ciclo de reinicio infinito (`Restart=on-failure`, cada 10s). Corregido con `chown -R quantum:quantum` sobre todo el directorio de `colector_ubuntu/` (no solo el log, para cubrir también `lecturas/`). Queda como advertencia para cualquier instalación futura de este servicio: revisar el dueño de `monitor.log` *antes* de arrancar si el directorio tuvo alguna corrida manual previa con otro usuario.
- Nota sobre conda: en MINI_LENOVO el shell interactivo tiene el ambiente `(base)` de conda activo, pero el `.service` usa `/usr/bin/python3` directo (no conda) y corrió sin problema — el colector solo usa librerías estándar de Python, así que no depende de conda. El tema conda pendiente (ver "Pendiente de decidir") no bloqueaba este paso.

**Paso 9 cerrado.**

## 10. Probar el flujo de actualización con el colector corriendo de forma persistente

- Con el colector ya corriendo solo (paso 9, no disparado a mano), confirmar que el ciclo completo sigue funcionando end-to-end con datos que llegan por su cuenta: colector → archivo → ingesta online → botón "Actualizar" → dashboard.
- Objetivo: validar el comportamiento real a lo largo del tiempo (varios intervalos, varios archivos) antes de mover nada de infraestructura.

## 11. Instalar el colector en un servidor offline de prueba y validar la carga offline

- Desplegar `colector_ubuntu` en un servidor de prueba sin conexión directa a la máquina central, generar lecturas reales, copiarlas manualmente a `ingesta/pendientes_offline/<nombre_servidor>/` y confirmar que el flujo de carga offline ya existente (paso 5) las procesa correctamente de punta a punta — no solo en teoría.
- Esto valida en la práctica la convención de carpetas que van a reutilizar tanto el relay (paso 14) como el script de carga remota (paso 13) — conviene probarla una sola vez bien, antes de automatizar algo encima.

### Probado ✅ (carga offline end-to-end, con QLYMSPROD01 real)

- `colector_ubuntu` corrido manualmente en **QLYMSPROD01** (servidor real de AbInBev, offline — ver nota en paso 3): generó 14 lotes reales (`thermal_zones` como método de CPU, `nvidia-smi` para GPU; sin `lm-sensors` instalado, el fallback funcionó igual).
- Los 14 `.csv` se copiaron a mano a `ingesta/pendientes_offline/QLYMSPROD01/` en la máquina central.
- **Bug encontrado y corregido**: `ingesta.py` calculaba `directorio_offline` como `PROJECT_DIR/pendientes_offline` (raíz del repo) en vez de `BASE_DIR/pendientes_offline` (dentro de `ingesta/`, donde realmente vive y donde ya apuntaba el `.gitignore`) — la ruta equivocada no existía, así que `procesar_offline()` no encontraba nada y no insertaba ni avisaba del error (fallaba en silencio). Como nunca se había probado este camino con datos reales (paso 5 solo probó online), el bug llevaba ahí desde que se escribió. Corregido en una línea (`BASE_DIR` en vez de `PROJECT_DIR`); requiere reiniciar el servicio `MonitServersV2_Backend` para tomar el cambio.
- Tras el fix: `POST /api/ingesta/ejecutar` devolvió `offline_cargados: 14`; la carpeta quedó vacía (borrado solo tras confirmar commit); Postgres quedó con 56 lecturas (14 archivos × 4 sensores) atribuidas correctamente a `QLYMSPROD01`.
- **Repetido con `lm-sensors` instalado** (no estaba presente en la primera prueba, el colector había caído al fallback `thermal_zones`): se instaló `lm-sensors` + `sensors-detect --auto` en QLYMSPROD01 (no se reinició ningún servicio del sistema, innecesario para esto). Nueva corrida del colector detectó correctamente `lm-sensors` (18 sensores reales: 2 paquetes de CPU + 12 núcleos + GPU, vs. los 4 del fallback). 10 archivos nuevos cargados igual de bien por el mismo flujo offline — total acumulado en Postgres: 206 lecturas de `QLYMSPROD01`.

**Paso 11 cerrado.**

## 12. Control de versiones y release notes

- Esquema de versionado (ej. semver `v1.0.0`) para coordinar releases — relevante en particular una vez que haya imágenes Docker con tags (paso 13).
- `release_notes.md` (o `CHANGELOG.md`): documentación legible de qué cambió en cada versión, distinta del log de git.
- Documentar la convención elegida en el README.
- Se hace antes de la migración a Docker (paso 13) a propósito, para que la primera imagen ya nazca con un tag de versión real.

## 13. Migrar el stack central (backend + dashboard + ingesta + BD) a DEVELOP, vía Docker

- **Contexto (2026-10-02)**: se decidió, en conjunto con el equipo, que el sistema central (hoy corriendo en la máquina Windows del usuario) se despliega en **DEVELOP** (Ubuntu Server) — uno de los propios servidores monitoreados — para no depender de que la máquina personal esté encendida. El empaquetado se hace con **Docker**.
- Esto es distinto de "instalar el servicio systemd del colector en DEVELOP" (paso 9) — ese es solo el colector de temperaturas; esto es mover el backend/API, el dashboard y la ingesta.
- Se hace después de los pasos 9-11 a propósito: migrar infraestructura es más seguro cuando la lógica de negocio (colector persistente, flujo de actualización, carga offline) ya está validada en el despliegue actual.

### Decisiones tomadas (migración a Docker)

1. **Todo el stack central se muda a DEVELOP** (no solo el backend): el objetivo explícito es que cualquiera del equipo pueda ver el dashboard sin depender de la máquina Windows del usuario.
2. **Postgres también se containeriza** — nada queda fuera de Docker. `docker-compose` con un servicio `postgres` (volumen persistente) + un servicio para el backend/dashboard, todo en DEVELOP.
3. **La ingesta periódica no toca el systemd del host**: en vez de un timer de systemd en el propio Ubuntu Server (que sí lo tocaría), se usa un **disparador 100% dentro de Docker** — un contenedor sidecar con un scheduler nativo de Docker (ej. [Ofelia](https://github.com/mcuadros/ofelia), pensado justo para esto: dispara `docker exec`/llamadas HTTP a otros contenedores por horario, vía labels en el propio `docker-compose.yml`, sin instalar ni configurar nada en el host). El systemd real del servidor queda intacto.
   - Nota técnica: systemd "de verdad" corriendo *dentro* de un contenedor es en sí mismo un anti-patrón (requiere modo privilegiado, no es como correrlo en una VM) — por eso la alternativa nativa de Docker, no una imitación de systemd en un contenedor.
4. El botón "Actualizar" del dashboard sigue funcionando igual (`POST /api/ingesta/ejecutar`), sin importar en qué máquina corra el backend.
5. El acceso al dashboard (hoy vía archivo hosts apuntando a `localhost`) pasaría a apuntar a la IP de DEVELOP — efecto buscado: cualquiera en la red lo ve, no solo la máquina del usuario.

### Nuevo requisito: cargar datos offline desde mi máquina

- Aunque el backend/BD vivan en DEVELOP, el usuario necesita poder seguir cargando los bundles de servidores offline (ver paso 14) **desde su propia máquina Windows**, sin tener que entrar por SSH a DEVELOP cada vez.
- **Decidido: opción (b)** — nunca se expone el puerto de Postgres a la red (queda solo accesible dentro de la red interna de Docker en DEVELOP). Se descartó la conexión directa por red (opción a) por el riesgo de exponer un puerto de base de datos en DEVELOP que además podría chocar con otras aplicaciones que ya corran ahí.
- **Script nuevo** (`cargar_offline_remoto.py` o similar, corre en la máquina Windows del usuario) que en un solo paso:
  1. Sube el bundle del servidor offline por SFTP (`paramiko`, igual que ya usa `ingesta.py`) directo a `pendientes_offline/<nombre_servidor>/` en DEVELOP (ruta montada como volumen de Docker — escribir ahí por SFTP equivale a escribir en la carpeta del contenedor).
  2. Dispara la carga llamando al mismo endpoint que ya usa el botón "Actualizar" del dashboard (`POST /api/ingesta/ejecutar`) — sin código nuevo en el backend, esa función ya procesa pendientes offline en la misma pasada que la ingesta online.
  3. Imprime en la terminal el resumen que ya devuelve ese endpoint (cargados/omitidos), sin necesidad de abrir el navegador.

### Pendiente de decidir (migración a Docker)

- Credenciales SFTP que usará el nuevo script de carga offline remota: ¿se reutilizan las mismas credenciales SSH que ya tiene DEVELOP en `inventario_servidores.yaml`, o se crea un usuario/acceso dedicado solo para esta tarea?
- Confirmar que DEVELOP tiene salida de red hacia todos los demás servidores monitoreados (hoy esa salida es desde la máquina Windows); para DEVELOP mismo ya no haría falta SSH a sí mismo si se lee directo del disco local.
- Manejo de secretos (`.env`) vía archivo de entorno de Docker Compose, nunca horneados en la imagen.
- Instalar Docker + Docker Compose en DEVELOP (Ubuntu Server — sin las restricciones de Control de Aplicaciones que sí tiene la máquina Windows).
- **Explorar usar `psycopg` v3** en vez de `psycopg2-binary`: la razón original para usar v2 fue que Control de Aplicaciones de Windows bloqueaba la DLL binaria de v3 en la máquina del usuario — esa restricción no existe en DEVELOP (Ubuntu Server), así que vale la pena revisar si conviene el cambio al dockerizar. No es necesario — lo que ya funciona en v2 sigue funcionando igual.

### README

- Agregar sección de instalación vía Docker: cómo construir/levantar los contenedores en DEVELOP, variables de entorno necesarias, cómo aplicar `db/schema.sql` al contenedor de Postgres.

## 14. Relay de datos para sitios offline / semi-offline

- **Contexto**: en AbInBev, varios servidores (QLYMSPROD01, 02, 03...) se ven entre sí en su propia red, pero el sitio completo es offline respecto a la máquina central. En otros 2 clientes hay un único servidor ("gateway") alcanzable online desde la máquina central; el gateway sí ve a sus compañeros en su LAN local, la máquina central no.
- Se construye después de los pasos 9-13 (ver arriba) — no se toca ningún servidor de producción de AbInBev ni de los otros 2 clientes hasta validar completo contra servidores de prueba.

### Decisiones tomadas (relay)

1. **Script de relay separado del colector** (decisión 2026-10-02, reemplaza la idea original de un "modo gateway" dentro de `monitor.py`): corre en el servidor "hub" (QLYMSPROD01 en AbInBev, o el gateway en los otros 2 clientes) como su **propio proceso/servicio systemd, independiente del colector**, con su propio intervalo (más espaciado que el del colector — ej. cada 2-4h en vez de cada hora, no hay urgencia de tenerlo al segundo). Se conecta por SSH/SFTP (mismo patrón `paramiko` que ya usa `ingesta.py`) a sus "compañeros" y descarga las lecturas pendientes de cada uno, dejándolas en subcarpetas locales nombradas igual que cada servidor — misma convención que ya usa `pendientes_offline/<nombre_servidor>/` (ej. `relay/<nombre_companero>/` dentro del hub). Separar esto del colector evita que una falla de red hacia un compañero (ej. caído) afecte la lectura de sensores propia del hub.
2. **Credenciales de los compañeros son variables por sitio** (en AbInBev ya hay llaves SSH sin password; en otros sitios se necesitará usuario/password) — viven en un archivo de configuración local en el propio servidor hub, nunca en el inventario central ni en git (no sale de ese servidor). Se documenta con una plantilla `.example` en el repo (mismo patrón que `inventario_servidores.yaml.example`), el archivo real nunca se versiona.
3. **Borrado**: el relay borra del servidor compañero solo tras confirmar que el archivo ya quedó bien guardado en el hub — mismo criterio idempotente que ya usa `ingesta.py` para no perder datos a medio camino.
4. **AbInBev (sitio 100% offline)**: disparo **manual** — el usuario entra por SSH a QLYMSPROD01 y corre el relay a mano cuando tiene acceso al sitio (igual que otras rutinas manuales que ya corre ahí). El bundle consolidado (carpeta `relay/` + lecturas propias del hub) se copia tal cual a `ingesta/pendientes_offline/` en la máquina central — el flujo offline ya existente lo absorbe **sin cambios**, porque ya espera justo esa estructura de subcarpetas por servidor (validado en la práctica en el paso 11, con datos reales de QLYMSPROD01).
5. **Clientes con gateway único (online)** (decisión 2026-10-02, reemplaza el disparo on-demand por SSH `exec_command` diseñado originalmente): el relay del gateway corre **de forma autónoma** en su propio ciclo (punto 1) — central ya no lo dispara ni espera a que termine. La ingesta online normal, al conectarse al gateway, **primero baja por SFTP toda la carpeta `relay/` a un staging local** (dentro de `ingesta/pendientes_offline/`) y **reutiliza tal cual `procesar_offline()`** (la misma función ya probada en el paso 11) para insertarla con la identidad correcta de cada compañero — sin lógica nueva de "atribuir carpeta a servidor", solo la descarga SFTP previa. Esto hace que el caso "offline total" (AbInBev) y el caso "online con gateway" terminen usando el mismo motor de carga; solo cambia cómo llegan los archivos a `pendientes_offline/` (USB a mano vs. SFTP automático).
6. El inventario central marca qué servidor es gateway de cuáles compañeros con un campo nuevo en la entrada del propio gateway: `es_gateway_de: [<nombre_companero_1>, <nombre_companero_2>, ...]` — así la ingesta online sabe, al conectarse a ese servidor, que debe esperar también la carpeta `relay/` con esos nombres.
7. Se asume **un solo gateway por sitio** (el modelo podría soportar varios a futuro, pero no hace falta ahora).

### Probado ✅ (script de relay, contra servidores de prueba: DEVELOP como hub, MINI_LENOVO como compañero)

- Construido [`relay/`](relay/): `relay.py` (SSH/SFTP vía `paramiko`, descarga a `.tmp` + rename atómico, borra del compañero solo tras confirmar escritura local), `config.ini` (intervalo propio), `companeros.yaml.example` (el real, gitignored, nunca en git — ver punto 2), `monit_servers_v2_relay.service`.
- **Prueba controlada**: se pausó temporalmente `activo: false` para MINI_LENOVO en el inventario real (para que la ingesta online normal no compitiera por los mismos archivos durante la prueba), se desplegó `relay.py` en DEVELOP con `MINI_LENOVO` como compañero en `companeros.yaml`, y se corrió manualmente.
- **Resultado**: `relay.py` descargó correctamente los `.csv` pendientes de MINI_LENOVO a `relay_entrante/MINI_LENOVO/` en DEVELOP y los borró del compañero tras confirmar la escritura local — sin pérdida de datos.
- **Validación de punta a punta** (simulando el caso AbInBev, sin construir todavía la pieza de Docker): los archivos de `relay_entrante/MINI_LENOVO/` se copiaron a mano a `ingesta/pendientes_offline/MINI_LENOVO/` en la máquina central (mismo patrón ya probado en el paso 11), se reactivó `activo: true` para MINI_LENOVO, y la ingesta cargó los 9 archivos relayados sin problema — cadena completa: colector → relay (recolecta y borra del compañero) → copia manual al hub de central → `procesar_offline()` → Postgres.

### Operativo ✅ en sitio real (AbInBev Zacatecas: QLYMSPROD01 + QLYMSPROD02, desde 2026-10-02)

- **QLYMSPROD01** (hub): colector propio + `relay.py` instalados como servicios `systemd` persistentes (`monit_servers_v2.service` y `monit_servers_v2_relay.service`), ambos `active (running)`. `companeros.yaml` apunta a `QLYMSPROD02` por llave SSH sin password (autenticación por `publickey`, confirmado en el log — `h0017909` es el mismo usuario en ambos servidores, sin passphrase en la llave).
- **QLYMSPROD02** (compañero): colector instalado como servicio `systemd` persistente desde cero, con `lm-sensors` real (no fallback).
- **Nota de despliegue — Python de conda vs. sistema**: a diferencia del colector (stdlib puro, corre bien con `/usr/bin/python3`), `relay.py` necesita `paramiko`/`pyyaml` — en QLYMSPROD01 esos paquetes solo quedaron instalados para el Python de conda (`pip install --user` con `(base)` activo), no para `/usr/bin/python3`. El `.service` del relay tuvo que apuntar explícitamente a `/home/h0017909/miniconda/bin/python3`. Ya documentado como comentario en la plantilla `relay/monit_servers_v2_relay.service`.
- **Bug de permisos de `monitor.log`/`relay.log` recurrente**: se repitió una vez más al desplegar en QLYMSPROD02 (y tras una reorganización de carpetas en QLYMSPROD01) — mismo fix de siempre (`chown -R` al usuario del servicio antes de reintentar).
- **Gotcha de `scp -r origen destino/`**: si `destino/` no existe todavía en el servidor remoto, `scp` no anida `origen` dentro de él — lo copia *como* `destino/`, aplanando su contenido. Pasó al copiar `colector_ubuntu/` de QLYMSPROD01 a QLYMSPROD02; se corrigió reorganizando manualmente. A tener en cuenta para futuros despliegues: crear primero el directorio destino, o revisar con `ls` tras el `scp`.
- **Primera recolección real confirmada**: con el colector de QLYMSPROD02 ya generando lotes reales, el relay recolectó 3 archivos a `relay_entrante/QLYMSPROD02/` en QLYMSPROD01 y los borró del compañero tras confirmar la escritura local.
- Inventario actualizado: `QLYMSPROD02` agregado (`activo: false`, mismo patrón que QLYMSPROD01); `QLYMSPROD01` con `es_gateway_de: [QLYMSPROD02]`.
- La carga a central **sigue siendo manual** (sitio 100% offline, por diseño — punto 4): copiar lecturas propias de QLYMSPROD01 + `relay_entrante/QLYMSPROD02/` a `pendientes_offline/` cuando se tenga acceso al sitio.

### Probado ✅ (caso gateway online, automatizado en `ingesta.py`, contra servidores de prueba)

- Construida `recolectar_relay_gateway()` en [`ingesta/ingesta.py`](ingesta/ingesta.py): se adelantó respecto al plan original (ya no se espera al paso 13/Docker, se hizo ahora porque no tiene dependencia real con la migración). Para cualquier servidor online con `es_gateway_de` en el inventario, `procesar_online()` ahora, después de bajar sus propios archivos, también baja por SFTP lo que el `relay.py` de ese gateway dejó en `directorio_relay/<nombre_companero>/` y lo deposita en `pendientes_offline/<nombre_companero>/` local (mismo patrón `.tmp` + rename atómico, borra del gateway solo tras confirmar escritura local) — `procesar_offline()` lo recoge en la misma corrida, sin copia manual.
- Nuevos campos de inventario documentados en `inventario_servidores.yaml.example`: `directorio_relay` (ruta de `relay_entrante/` en el gateway) y `es_gateway_de` (lista de nombres de compañeros).
- **Prueba controlada**: `DEVELOP` configurado temporalmente como gateway de `MINI_LENOVO` (pausado con `activo: false` durante la prueba), con `relay.py` instalado como servicio persistente en DEVELOP por primera vez.
- **Resultado**: con archivos ya esperando en `relay_entrante/MINI_LENOVO/` en DEVELOP, el botón "Actualizar" disparó la ingesta, que bajó y borró automáticamente los archivos del gateway, y los cargó a Postgres en la misma pasada — **sin ninguna intervención manual**. (Recordatorio operativo: tras editar `ingesta.py` hace falta reiniciar el servicio `MonitServersV2_Backend` para que tome el cambio — se nos olvidó la primera vez y la ingesta siguió corriendo el código viejo silenciosamente.)
- **Nota menor, no es un bug de datos**: un archivo que `procesar_offline()` omite por `ya_ingerido` (ya cargado antes bajo ese mismo nombre) no se borra del disco — queda huérfano en `pendientes_offline/`. Pasó en esta prueba porque el relay recolectó de nuevo unos archivos viejos que nunca se habían limpiado de `relay_entrante/` en DEVELOP (se habían copiado a mano antes, no movido). Sin impacto en la BD (correctamente no duplicado); limpieza de huérfanos queda como housekeeping manual ocasional, no bloquea nada.
- Configuración de prueba revertida tras validar (inventario de DEVELOP/MINI_LENOVO de vuelta a la normalidad; servicio de relay de prueba en DEVELOP detenido y deshabilitado).

### Pendiente

- Validar contra un **gateway real** de uno de los otros 2 clientes — el mecanismo completo (`relay.py` + la pieza de `ingesta.py`) ya está construido y probado; falta el nombre/IP real del gateway y sus compañeros, y desplegar igual que se hizo con AbInBev.

## 15. Validación end-to-end (opcional, recomendado)

- Prueba completa del flujo: colector → ingesta → BD → dashboard, con al menos un servidor Ubuntu y uno Windows reales antes de dar el proyecto por cerrado.

## Pendiente de decidir

- Valores exactos de los umbrales de temperatura para el semáforo (paso 6, backend) — ya se decidió que viven en un YAML leído por el backend (`backend/umbrales.yaml`); los que hay ahí son provisionales (70/85°C CPU, 75/85°C GPU).
- ~~Detalles de la imagen empresarial Quantum a aplicar (paso 7).~~ Resuelto — colores, logo y tipografía reales ya aplicados en el dashboard (paso 7).
- **Ambiente conda para `colector_ubuntu`** (paso 1 / instalación): el usuario quiere que la instalación en servidores use un ambiente virtual con conda antes de todo. Pendiente: por qué `conda` no aparece en DEVELOP (`which conda` no encontró nada, ni en rutas comunes) — el usuario lo va a verificar. Una vez resuelto, falta decidir nombre del ambiente y versión de Python, y documentarlo en el README. No bloquea el paso 9 — puede resolverse en paralelo.

## Mejoras futuras (no bloquean el roadmap)

- Migrar la autenticación SSH de usuario/password a llaves públicas/privadas (más seguro; no es necesario para el objetivo actual de no subir secretos a GitHub).
