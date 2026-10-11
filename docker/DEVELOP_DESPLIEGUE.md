# Despliegue en DEVELOP — lo que sabemos y el plan a seguir

> Paso 13 del ROADMAP, ahora contra el servidor real (no la VM de prueba). Este documento junta
> todo lo que ya se confirmó de DEVELOP (revisión de solo lectura, 2026-10-11) y el plan paso a
> paso — con sus verificaciones — para instalar ahí el stack de Monit_Servers_V2. **Nada de esto
> se ha ejecutado todavía** salvo lo marcado explícitamente como hecho.

## 1. Lo que ya sabemos de DEVELOP

### Sistema

| | |
|---|---|
| SO | Ubuntu 22.04.5 LTS (mismo que la VM de prueba) |
| Kernel | 5.15.0-186-generic |
| Hostname | `develop` |
| CPU | 20 núcleos |
| RAM | 62 GB total (~30 GB en uso por otras cargas ya corriendo ahí) |
| Swap | 8 GB (7 GB en uso — swap ya bastante ocupado, señal de que la máquina está cargada) |

### Disco — punto de atención real

| Punto de montaje | Uso | Libre |
|---|---|---|
| `/` | 45% | 109 GB |
| `/home` | **92%** | 16 GB |
| `/opt` (destino elegido) | **90%** | 34 GB |
| `/mnt/disco2T` (ahí vive el `data-root` de Docker) | **96%** | 75 GB |

Ningún punto de montaje está crítico para nuestro stack (Postgres + backend son ligeros), pero no
hay margen de error — un backup o volumen que crezca sin control ahí sí sería un problema para
**todos** los demás productos que comparten esos discos, no solo el nuestro.

### Red

- **ZeroTier, interfaz `ztnfaoizvo`**: IP **estática** `192.168.192.205/24` (confirmado — sin flag
  `dynamic`, a diferencia de la interfaz de red normal `enp11s0`, que sí es DHCP). Es la IP que ya
  usa todo el inventario para llegar a DEVELOP.
- **Confirmado, alcanza el segmento `192.168.192.x`** (ej. MINI_LENOVO, `192.168.192.233` — ping
  exitoso).
- **Confirmado, NO alcanza el segmento `192.168.194.x`** (TAD_18_de_Marzo, `192.168.194.15` — 100%
  de paquetes perdidos). Esto es un tema de ruteo/membresía de ZeroTier, **fuera del alcance de
  Docker** — no bloquea instalar el stack, pero sí bloquea que la ingesta online de ese servidor
  en particular funcione desde DEVELOP hasta que se resuelva aparte.
- Otras interfaces presentes (no relevantes para nosotros, son de otros productos): `docker0`
  (172.17.0.1/16, bridge default de Docker), `br-3bbe8b4296b3` (192.168.0.1/24, red Docker
  personalizada de otro producto).

### Docker — ya instalado y en uso activo por otros

- **Docker 28.2.2 + Compose v2.33.1** (plugin, `docker compose`, igual que usamos en la VM de
  prueba).
- **`/etc/docker/daemon.json` ya existe**, con configuración de otros:
  ```json
  {
    "max-concurrent-downloads": 4,
    "runtimes": { "nvidia": { "path": "/usr/bin/nvidia-container-runtime", "runtimeArgs": [] } },
    "data-root": "/mnt/disco2T/docker"
  }
  ```
  Sin entrada `"dns"` — a diferencia de la VM de prueba, donde tuvimos que agregarla a mano.
  **Hay que probarlo antes de asumir que no hará falta** (ver plan, paso 2).
- **No es un host dedicado a nosotros**: ~20 contenedores de otros productos de Quantum corriendo
  ahí ahora mismo (`qface-server`, `vision-stream`, `qplate-server`, `event-stream`, `robot`,
  `plate-reader`, `qr-reader`, varias bases Postgres/SQL Server/Redis de distintos clientes).
  **No se toca ninguno de ellos.**
- **Ya existe una red Docker llamada literalmente `quantum-network`** (bridge, `192.168.0.0/24`,
  creada por otro producto directamente con `docker network create`, no vía Compose). No es un
  choque real: Compose nombra sus redes con el prefijo del proyecto (ej.
  `monit-servers-v2_quantum-network`), así que no colisiona — pero hay que evitar confundirla en
  `docker network ls`.
- **Puerto 8000 confirmado libre** (sin colisión con los ~20 contenedores existentes). Se vuelve a
  confirmar en el momento real de instalar, por si algo cambió.
- El grupo `docker` (gid 999) ya tenía a `fgerard`, `safr`, `fgv`; el usuario de servicio
  `quantum` **no** estaba en ese grupo.

### Usuarios

- **`quantum`**: cuenta de servicio existente, en grupo `sudo`, dueña de `/home/quantum` y del
  colector `monit_servers_v2.service` ya instalado (paso 9 del ROADMAP — no se toca).
- **`fgerard`** / **`fgv`**: cuentas personales que comparten el grupo `quantum` (gid 1000) como
  grupo primario — un caso aparte, no la convención general del servidor.
- **`fnoria`, `jnoria`, `safr`, `yms_consulta`**: cada uno con su **propio grupo exclusivo**
  (mismo nombre que el usuario) — esta es la convención real y correcta del servidor.
- **`imedina`** (creado 2026-10-11, ✅ ya hecho): uid 1007, grupo primario exclusivo `imedina`
  (gid 1006, no comparte con nadie), grupos secundarios `sudo` y `docker`, home `/home/imedina`
  en `750` (`imedina:imedina`, confirmado sin acceso de otros usuarios ni a ni desde su home).
  Contraseña ya configurada. Verificado: puede correr `docker`/`docker compose` sin `sudo`, y
  **no** puede leer `/home/fgerard` ni ningún otro home ajeno.

### Servicios existentes relevantes

- `monit_servers_v2.service` — nuestro colector (paso 9 del ROADMAP), activo, **no se toca**.
- `monit.service` — el daemon genérico de Linux "monit" (coincidencia de nombre, no es nuestro).

## 2. Decisiones ya tomadas para este despliegue

1. **Ruta de instalación: `/opt/quantum/monit-servers-v2`** (no `/home/imedina/...`) — sigue la
   misma convención que ya usan los demás productos de Quantum en este servidor
   (`server-setup.sh` instala en `/opt/quantum/<producto>`), y no ata el despliegue al ciclo de
   vida de una cuenta personal. Decisión tomada el 2026-10-11 tras comparar ambas opciones.
2. **Usuario: `imedina`**, ya creado y verificado, con `docker` para correr los contenedores sin
   `sudo` y `sudo` para las tareas de instalación (crear carpetas en `/opt`, etc.).
3. **Secretos**: `.env`/`inventario_servidores.yaml` reales en `/opt/quantum/monit-servers-v2/`
   se dejan en modo `0600` (solo lectura/escritura para el dueño del archivo) — aunque `/opt`
   suele ser legible por todos, el contenido sensible queda protegido igual a nivel de archivo.
4. **Nada de scp ad-hoc**: a diferencia de la VM de prueba (donde copiamos archivos sueltos por
   SFTP y eso arrastró `ingesta.log`/`service.log` reales a la imagen por error), aquí se clona el
   repo real con `git clone` — un checkout limpio no tiene esos archivos (están en `.gitignore`),
   así que ese bug específico no se puede repetir.
5. **Credenciales de Postgres de producción**: nuevas, generadas para esta instalación — no se
   reutiliza la contraseña de prueba (`monit_srv_test` / `PruebaDocker2026!`) que usamos en la VM.
6. **Imagen de Postgres: `postgres:18`, no `postgres:16`** (el que usó la prueba en la VM) —
   comparado el 2026-10-11 el `pg_dump --schema-only` de producción (Windows) contra el de la VM:
   **estructuralmente idénticos** (mismas tablas, columnas y constraints; las únicas diferencias
   del diff eran cosméticas — tokens aleatorios de seguridad que genera cada corrida de `pg_dump`,
   y una forma distinta de imprimir la misma expresión `CHECK`). La única discrepancia real:
   producción corre **PostgreSQL 18.6**, confirmado con `SELECT version();`. `docker-compose.yml`
   ya se actualizó a `postgres:18` para no introducir una diferencia de versión evitable entre la
   prueba y el despliegue real. Los datos en sí sí difieren (la VM tiene datos de prueba propios
   cargados el 2026-10-11, además del backup base) — se resuelve solo con el corte final de datos
   reales en el Paso 6.

## 3. Plan paso a paso (con verificación en cada punto)

Mismo espíritu que `PLAN_PRUEBA_DOCKER.md`, adaptado a que aquí Docker **ya está instalado** y el
servidor **ya está en producción para otros** — cada paso valida antes de seguir, y nada debe
afectar a los contenedores/servicios que ya corren ahí.

### Paso 0 — Dar de baja `TAD_18_de_Marzo` (PoC de PEMEX terminada)

**Contexto (2026-10-11)**: la PoC en el sitio de PEMEX (`TAD_18_de_Marzo`) terminó. La máquina ya
no pertenece a la red de ZeroTier que la conectaba (`192.168.194.0`, red `4753cf475f2eed8a`) — se
intentó reincorporar a DEVELOP a esa red para la ingesta online, pero ya no tiene sentido
perseguirlo si el servidor monitoreado se va a dar de baja de todos modos. Se hace **antes** de
migrar los datos a DEVELOP, para no arrastrar ahí información de un sitio ya cerrado.

1. En la máquina Windows (donde vive la base de datos de producción real todavía):
   `pipenv run python db/gestionar_servidor.py baja TAD_18_de_Marzo` — borra sus lecturas, uso de
   disco, archivos ya ingeridos, hardware/umbrales (cascada) y la fila de `servidores`; limpia
   también el grupo `PEMEX` si queda vacío. Pide confirmación explícita (`escribe 'si'`) antes de
   borrar.
   - **Bug encontrado y corregido antes de usarlo**: `cmd_baja()` no borraba `uso_disco` (esa
     tabla no tiene `ON DELETE CASCADE`, a diferencia de `hardware_cpu`/`discos`/etc. — se agregó
     en el paso 16, después de escribirse esta función, y se quedó fuera). Sin el fix, el borrado
     fallaría a medias por la restricción de llave foránea en cuanto `TAD_18_de_Marzo` tuviera
     uso de disco cargado (como ya lo tiene).
2. Quitar la entrada `TAD_18_de_Marzo` de `inventario_servidores.yaml` (el script no toca el
   inventario, lo dice explícitamente al pedir confirmación).
3. **Verificación**: `TAD_18_de_Marzo` ya no aparece en el árbol de servidores del dashboard ni en
   `GET /api/servidores`; una corrida de la ingesta no vuelve a darlo de alta solo porque ya no
   está en el inventario.

### Paso 1 — Preparar el directorio

1. `sudo mkdir -p /opt/quantum/monit-servers-v2`
2. `sudo chown imedina:imedina /opt/quantum/monit-servers-v2`
3. **Verificación**: `ls -ld /opt/quantum/monit-servers-v2` → dueño `imedina`, sin afectar nada
   más en `/opt`.

### Paso 2 — Confirmar el DNS de Docker en DEVELOP

El `daemon.json` actual no tiene `"dns"` configurado — a diferencia de la VM, donde sin eso los
builds fallaban (`Temporary failure resolving`). Antes de construir nuestra imagen:

1. `docker run --rm alpine:3 sh -c 'cat /etc/resolv.conf; nslookup deb.debian.org'` (como
   `imedina`, sin tocar nada).
2. **Si resuelve bien**: no se toca `/etc/docker/daemon.json` (ya tiene configuración de otros
   runtimes/rutas, no hay que arriesgarse a romperla).
3. **Si falla igual que en la VM**: en vez de sobreescribir el `daemon.json` existente, se le
   agrega la clave `"dns"` a la configuración ya existente (merge, no reemplazo) y se reinicia
   Docker — avisando antes, porque reiniciar el daemon de Docker afecta a los ~20 contenedores de
   otros productos (la mayoría tienen `restart: always`/similar y deberían volver solos, pero es
   una acción que toca todo el host, no solo lo nuestro).

### Paso 3 — Clonar el repositorio

1. Como `imedina`: `cd /opt/quantum/monit-servers-v2 && git clone <url-del-repo> .` (o el método
   de acceso que ya se use para este repo — a confirmar si es HTTPS con token o llave SSH).
2. **Verificación**: `ls` muestra `backend/`, `dashboard/`, `ingesta/`, `db/`, `docker/`, etc.;
   `git status` limpio; **no** aparecen `.env`, `inventario_servidores.yaml`, `ingesta.log` ni
   `backend/service.log` (confirmaría que `.gitignore` hizo su trabajo).

### Paso 4 — Secretos y configuración real

1. Crear `.env` (credenciales de Postgres de producción, nuevas) e
   `inventario_servidores.yaml` (copiar del real que ya existe en la máquina Windows, o
   regenerar) dentro de `/opt/quantum/monit-servers-v2/`.
2. Crear `docker/.env` (credenciales que usará `docker-compose.yml` para levantar Postgres).
3. `chmod 600` a ambos archivos.
4. **Verificación**: `ls -la` confirma `-rw-------` en ambos; `cat` desde otro usuario sin
   privilegios (ej. probar brevemente que ni siquiera el grupo `imedina` los puede leer, ya que
   son exclusivos de un solo archivo).

### Paso 5 — Confirmar que no hay colisión de puertos/red

1. `ss -tlnp | grep 8000` (y cualquier otro puerto que vayamos a publicar) → debe seguir libre.
2. `docker network ls` → confirmar que Compose va a crear su propia red con prefijo de proyecto,
   sin tocar la `quantum-network` ya existente de otro producto.

### Paso 6 — Levantar Postgres y restaurar/migrar los datos reales ✅

1. `docker compose up -d postgres` (desde `/opt/quantum/monit-servers-v2/docker/`).
2. **Verificación**: `docker compose logs postgres` sin errores; `\dt` muestra las 13 tablas del
   esquema.
3. Backup fresco de producción (`db/respaldar.py`, ya sin `TAD_18_de_Marzo`) restaurado —
   123,419 lecturas, 11 servidores.

**Bug encontrado y corregido (real, no de la VM)**: `postgres:18` cambió su layout a uno
compatible con `pg_ctlcluster` ([docker-library/postgres#1259](https://github.com/docker-library/postgres/pull/1259))
— montar el volumen en `/var/lib/postgresql/data` (lo que funcionaba con `postgres:16`, usado en
la prueba de la VM) hace que el contenedor **aborte al iniciar** con un error claro. Corregido en
`docker-compose.yml`: el volumen ahora monta en `/var/lib/postgresql` directo. No se detectó en la
prueba de la VM porque ahí se usó `postgres:16` — se homologó a `postgres:18` justo antes de este
despliegue (ver sección 2, punto 6) y el bug salió a la primera.

### Paso 7 — Construir y levantar el backend ✅

1. `docker compose up -d --build backend`.
2. **Verificación**: `docker compose logs backend` sin tracebacks; `curl` a
   `http://127.0.0.1:8000/api/servidores` responde con datos reales; `ls -la` dentro del
   contenedor en `ingesta/` confirma que no se coló ningún archivo con permisos de `root` (el
   `git clone` limpio evitó el bug que sí nos pasó en la VM).

**Detalle encontrado y corregido**: `ingesta/pendientes_offline/` no existe como carpeta en el
repo (git no versiona carpetas vacías, y está en `.gitignore`) — al no existir en el host al
hacer `docker compose up`, Docker la creó solo como bind mount, **con dueño `root:root`**. El
contenedor corre como uid 1000 y no podría escribir ahí (necesario para que
`recolectar_relay_gateway()` deposite los archivos que recolecta de los compañeros de
`quantumdata`/`apiman-fase1`). Corregido con `chown -R imedina:imedina` sobre esa carpeta antes de
probar la ingesta. A tener en cuenta para cualquier despliegue futuro desde un `git clone` limpio:
crear esa carpeta con el dueño correcto *antes* del primer `docker compose up`, en vez de dejar
que Docker la auto-cree.

### Paso 8 — Validar ingesta online real (sin túnel esta vez)

A diferencia de la VM de prueba, DEVELOP ya tiene ZeroTier real — no hace falta ningún túnel SSH.

1. `POST /api/ingesta/ejecutar` (o esperar al scheduler si para entonces ya está Ofelia).
2. **Verificación**: `ingesta.log` dentro del contenedor muestra conexión exitosa a los
   servidores del segmento `192.168.192.x`; se espera que **falle** (esperado, no es un bug) la
   conexión a `TAD_18_de_Marzo` (`192.168.194.x`) hasta que se resuelva el alcance de red aparte.

### Paso 9 — Checklist final antes de dar el despliegue por cerrado

- [ ] `docker compose down` / `up` no pierde datos.
- [ ] Reiniciar el contenedor del backend (no el host completo — no hay necesidad de reiniciar
      todo DEVELOP solo por esto) y confirmar que vuelve solo.
- [ ] Dashboard visualmente correcto, confirmado por el usuario.
- [ ] Ninguno de los ~20 contenedores preexistentes se vio afectado (`docker ps` antes/después,
      mismo conteo y mismos nombres corriendo).
- [ ] Espacio en disco revisado una vez más tras la carga de datos real.

## 4. Qué NO se hace en este plan (a propósito)

- No se resuelve el alcance de red a `192.168.194.0` (TAD_18_de_Marzo) — es un tema de
  ZeroTier/ruteo, independiente de Docker.
- No se toca ningún contenedor, red, ni archivo de otros productos ya corriendo en DEVELOP.
- No se instala todavía el scheduler Ofelia (la ingesta se dispara a mano o vía el botón
  "Actualizar", igual que en la prueba de la VM) — se agrega en una iteración posterior.
- No se apaga el stack actual en la máquina Windows (NSSM + tarea programada) hasta confirmar que
  DEVELOP funciona de punta a punta con datos reales.
- No se modifica `/etc/docker/daemon.json` salvo que el paso 2 confirme que de verdad hace falta,
  y en ese caso como un *merge*, nunca un reemplazo.
