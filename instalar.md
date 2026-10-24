# Instalar un servidor nuevo

Guía operativa para dar de alta un servidor Linux nuevo en el sistema de monitoreo, en
cualquiera de sus 4 variantes — desde instalar el colector hasta que aparezca con datos
reales, hardware, umbrales y (si aplica) el botón "Tiempo Real" funcionando en el dashboard.

Este documento asume que el stack central (Postgres + backend/dashboard + ingesta) ya está
corriendo en Docker, en DEVELOP (`192.168.192.205`, dashboard en `http://192.168.192.205:8000`)
— ver [`README.md`](README.md) si hace falta levantar ese stack desde cero.

## Qué variante te aplica

| Tu situación | Variante |
| --- | --- |
| El servidor nuevo es alcanzable por SSH directo desde DEVELOP | **A — Directo** |
| El servidor nuevo solo es alcanzable desde la LAN de otro servidor que **ya** es gateway de un sitio existente (ej. un 4º compañero de `quantumdata`) | **B — Compañero de un gateway existente** |
| Vas a dar de alta un sitio nuevo completo (un gateway/hub + sus propios compañeros) | **C — Sitio relay nuevo** |
| El servidor nuevo no tiene NINGUNA ruta de red hacia DEVELOP, ni directa ni vía otro servidor (sitio 100% offline, tipo AbInBev) | **D — 100% offline** |

Las 4 variantes instalan el colector igual (prerrequisitos + Parte 0 de abajo); lo que cambia
es cómo se da de alta en el inventario central y cómo llegan los datos a Postgres.

---

## 0. Prerrequisitos comunes (todas las variantes)

En el servidor Linux nuevo (por SSH):

```bash
# Python 3 (normalmente ya viene instalado)
python3 --version

# CPU Intel/AMD: instalar lm-sensors
sudo apt install lm-sensors
sudo sensors-detect
# Responde "yes"/Enter a las preguntas por defecto. Al final pregunta si quiere
# agregar modulos a /etc/modules -- acepta (yes).

# CPU ARM: no se requiere nada adicional, el colector usa /sys/class/thermal
# del kernel directamente (thermal_zones).

# GPU NVIDIA (opcional): confirma que el driver expone nvidia-smi
nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits
```

Verifica manualmente qué método va a detectar el colector:

```bash
sensors                                      # CPU Intel/AMD (lm-sensors)
ls /sys/class/thermal/ | grep thermal_zone   # CPU ARM (fallback)
```

Si ninguno de los dos da resultado, el colector no podrá leer temperatura de CPU y abortará
con un mensaje claro al correrlo. GPU es opcional — un servidor sin GPU simplemente no genera
esos sensores. El mismo colector también lee el **uso de disco** por punto de montaje (vía
`/proc/mounts`) sin nada adicional que instalar.

**Instalar el colector** (igual en las 4 variantes):

1. Copia la carpeta [`colector_ubuntu/`](colector_ubuntu/) completa (`monitor.py`, `config.ini`,
   `monit_servers_v2.service`) al servidor, por ejemplo a
   `/home/<usuario>/check/monit_servers_v2/colector_ubuntu/` (usa el usuario real de ese
   servidor — `quantum` es el estándar en servidores propios de Quantum, pero en servidores de
   cliente puede ser otro, ej. `h0017909` en AbInBev).

2. Edita `config.ini`:

   ```ini
   [monitoreo]
   intervalo_minutos = 60

   [almacenamiento]
   directorio_salida = /home/<usuario>/check/monit_servers_v2/colector_ubuntu/lecturas
   ```

   **Importante**: `directorio_salida` debe coincidir EXACTO con el `directorio_remoto` que vas
   a poner en el inventario central más abajo — si no coinciden, la ingesta nunca encuentra los
   archivos (falla en silencio, sin error visible).

3. Pruébalo a mano ANTES de instalar el servicio:

   ```bash
   cd /home/<usuario>/check/monit_servers_v2/colector_ubuntu
   python3 monitor.py
   ```

   En otra terminal: `tail -f monitor.log` (debe indicar el método de CPU detectado) y
   `ls lecturas/` (debe empezar a aparecer `lecturas_<fecha>.csv` y `disco_<fecha>.csv`).
   Ctrl+C una vez confirmado.

4. Instala el servicio systemd:

   ```bash
   nano monit_servers_v2.service   # ajusta usuario/rutas si difieren de 'quantum'/'check/...'
   sudo cp monit_servers_v2.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable monit_servers_v2
   sudo systemctl start monit_servers_v2
   sudo systemctl status monit_servers_v2   # debe quedar "active (running)"
   ```

   > ⚠️ **No agregues** `StandardOutput=append:.../monitor.log` ni `StandardError=...` al
   > `.service`. systemd crearía ese archivo él mismo como root antes de bajar privilegios al
   > usuario configurado, y como `monitor.py` también lo abre por su cuenta
   > (`logging.basicConfig`), el segundo intento choca contra el dueño root y el servicio entra
   > en loop de reinicio. La plantilla actual ya no trae esas líneas — no las repongas.
   >
   > Si queda `activating (auto-restart)` en vez de `active (running)`, revisa el dueño de
   > `monitor.log`: `sudo chown <usuario>:<usuario> monitor.log && sudo systemctl restart monit_servers_v2`.

Con esto el colector ya está generando datos localmente. Lo que sigue depende de la variante.

---

## Variante A — Servidor directo (online, alcanzable por SSH desde DEVELOP)

### A.1 Alta en el inventario central

Edita `inventario_servidores.yaml` (en DEVELOP: `/opt/quantum/monit-servers-v2/inventario_servidores.yaml`):

```yaml
  - nombre: <NOMBRE_SERVIDOR>
    grupo: <Cliente>/<Sitio>        # ej. "Quantum", "AbInBev/Zacatecas" -- arma el arbol del dashboard
    sistema_operativo: ubuntu
    activo: true
    ip: <ip_real>
    puerto: 22
    usuario: <usuario_ssh>
    password: <password_ssh>
    directorio_remoto: /home/<usuario>/check/monit_servers_v2/colector_ubuntu/lecturas
```

- `nombre` debe ser único — es el identificador que vas a usar en todos los pasos siguientes
  (hardware, umbrales, hostname del `.json`, URL de la API).
- `directorio_remoto` debe ser idéntico al `directorio_salida` del `config.ini` del colector.
- No hace falta reiniciar ni reconstruir nada del backend — el archivo se lee del disco en cada
  petición (está montado como volumen de Docker, no horneado en la imagen).

### A.2 Disparar la ingesta una vez

Agregar el servidor al YAML no lo da de alta solo en Postgres — necesita que corra la ingesta
una vez:

```bash
curl -X POST http://192.168.192.205:8000/api/ingesta/ejecutar
```

(o espera el ciclo automático de Ofelia, cada hora en punto; o el botón "Actualizar" del
dashboard). Verifica que el servidor aparece en el árbol del dashboard, dentro del grupo
configurado, con temperatura y uso de disco reales.

### A.3 "Tiempo Real" — ya funciona solo

Para un servidor `activo: true` sin relación de gateway, el botón "Tiempo Real" del dashboard
queda habilitado automáticamente, sin ningún paso adicional — reusa las mismas credenciales SSH
de arriba. Confírmalo:

```bash
curl -s http://192.168.192.205:8000/api/servidores/<NOMBRE_SERVIDOR>/tiempo_real/disponible
# {"disponible":true,"motivo":null}
```

> Si el `curl` no contesta nada: revisa si DEVELOP tiene `BIND_IP` configurado a una IP
> distinta de `127.0.0.1`/`localhost` en `docker/.env` — en ese caso el puerto 8000 solo
> escucha en esa IP, no en `localhost` (`docker compose ps` te muestra el bind real).

Continúa en [Hardware y umbrales](#hardware-y-umbrales-las-4-variantes) y el
[checklist final](#checklist-final-de-verificación).

---

## Variante B — Compañero detrás de un gateway YA existente

Para agregar un servidor nuevo a un sitio que **ya** tiene su gateway/hub funcionando (ej. un
4º servidor en la LAN de `quantumdata`, que ya es gateway de `colima00/01/02`).

### B.1 Instalar el colector en el compañero

Igual que la Parte 0 — pero este servidor normalmente **no** es alcanzable directo desde
DEVELOP (por eso necesita el relay), así que despliega los archivos del colector por el medio
disponible hacia ese sitio (USB, u otro servidor del mismo sitio que sí tenga acceso).

### B.2 Agregarlo a `companeros.yaml` DEL GATEWAY

**Esto se edita EN el gateway, nunca en el inventario central** — `relay/companeros.yaml` vive
solo ahí (gitignored, nunca sube a git ni al inventario central):

```yaml
companeros:
  # ... los que ya existian ...
  - nombre: <nombre_companero>
    ip: <ip_o_hostname_del_companero_en_la_LAN>
    puerto: 22
    usuario: <usuario>
    password: <password_o_vacio_si_usa_llave>   # vacio -> paramiko usa la llave SSH por defecto / el agente
    directorio_remoto: /home/<usuario>/monit_servers_v2/colector_ubuntu/lecturas
```

No hace falta reiniciar el servicio `monit_servers_v2_relay` — `relay.py` relee este archivo en
cada ciclo (cada `intervalo_minutos`, ver `relay/config.ini` de ese gateway).

### B.3 Alta del compañero en el inventario central

En el inventario central (el mismo de siempre, en DEVELOP), agrega la entrada del compañero —
**siempre** `activo: false`, nunca se conecta directo a él:

```yaml
  - nombre: <nombre_companero>
    grupo: <Cliente>/<Sitio>        # mismo grupo que el gateway, normalmente
    sistema_operativo: ubuntu
    activo: false
    ip:
    puerto:
    usuario:
    password:
    directorio_remoto: /home/<usuario>/monit_servers_v2/colector_ubuntu/lecturas
```

Y agrégalo a la lista `es_gateway_de` de la entrada del gateway correspondiente (ya existente):

```yaml
  - nombre: <nombre_gateway>
    ...
    es_gateway_de: [colima00, colima01, colima02, <nombre_companero>]   # el nuevo, agregado a la lista
```

### B.4 Verificar que el relay ya lo recolecta

```bash
# en el gateway:
tail -f relay.log   # debe mostrar "Recolectado: <archivo>" para el companero nuevo
ls relay_entrante/<nombre_companero>/
```

Dispara la ingesta (`curl -X POST http://192.168.192.205:8000/api/ingesta/ejecutar`) y confirma
que aparece en el dashboard con datos reales.

### B.5 "Tiempo Real"

Si el gateway **ya tiene** `ruta_repo` configurado (porque ya soporta Tiempo Real para sus
otros compañeros), no hace falta tocar nada más — el compañero nuevo queda habilitado solo, ya
que `backend/ssh_lectura_directa.py` resuelve el caso dinámicamente contra `es_gateway_de` en
cada petición. Confírmalo:

```bash
curl -s http://192.168.192.205:8000/api/servidores/<nombre_companero>/tiempo_real/disponible
curl -s http://192.168.192.205:8000/api/servidores/<nombre_companero>/tiempo_real/lectura
```

Si el gateway **todavía no tiene** `ruta_repo` (porque este es el primer compañero del sitio
que intenta usar Tiempo Real), sigue la sección C.4-C.5 de la Variante C de abajo — es
exactamente el mismo procedimiento, el gateway ya existe, solo falta esa pieza.

Continúa en [Hardware y umbrales](#hardware-y-umbrales-las-4-variantes).

---

## Variante C — Sitio relay nuevo (gateway + sus propios compañeros)

Para dar de alta un sitio completo nuevo, donde ningún servidor existía antes en el inventario.

### C.1 Instalar el colector en el gateway y en cada compañero

Parte 0, en **todos** los servidores del sitio — el gateway también corre su propio colector
(además de `relay.py`), igual que cualquier servidor "directo".

### C.2 Instalar `relay.py` en el gateway

Requisitos — a diferencia del colector (stdlib puro), `relay.py` necesita `paramiko`/`pyyaml`:

```bash
python3 -c "import paramiko, yaml" || sudo apt install python3-paramiko python3-yaml
```

> ⚠️ En Ubuntu 23.04+/Debian 12+, `pip3 install paramiko pyyaml` falla con
> `error: externally-managed-environment` (PEP 668) — usa el paquete de `apt` de arriba. Si no
> alcanza (versión vieja), la alternativa es `pip3 install --break-system-packages paramiko pyyaml`,
> o un venv dedicado apuntando `ExecStart` del `.service` a `<venv>/bin/python3`.
>
> ⚠️ Si el servidor usa **conda**, verifica que el `python3` que pongas en `ExecStart` sea el
> mismo donde quedaron instalados esos paquetes (`<python3_elegido> -c "import paramiko, yaml"`).

Copia la carpeta [`relay/`](relay/) (`relay.py`, `config.ini`, `monit_servers_v2_relay.service`)
al gateway, ej. a `/home/quantum/monit_servers_v2/relay/`.

Crea `companeros.yaml` a partir de [`companeros.yaml.example`](relay/companeros.yaml.example)
(con las credenciales reales de cada compañero de este sitio — ver formato en B.2 de arriba).

Instala el servicio (misma advertencia de `StandardOutput`/`StandardError` que el colector):

```bash
nano monit_servers_v2_relay.service   # ajusta usuario/rutas/python3
sudo cp monit_servers_v2_relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable monit_servers_v2_relay
sudo systemctl start monit_servers_v2_relay
sudo systemctl status monit_servers_v2_relay
tail -f relay.log   # debe mostrar "Recolectado: <archivo>" por cada companero
```

### C.3 Alta del gateway y sus compañeros en el inventario central

El gateway, `activo: true` con sus credenciales reales, más `directorio_relay` y
`es_gateway_de`:

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

Cada compañero, `activo: false` (igual que B.3). Dispara la ingesta y confirma en el dashboard
que el gateway y sus compañeros ya traen datos reales (`recolectar_relay_gateway()` en
`ingesta/ingesta.py` baja sola por SFTP lo que el relay dejó en `directorio_relay/<companero>/`).

### C.4 Desplegar lo necesario para "Tiempo Real" en el gateway

El gateway necesita, además de lo de C.2, dos cosas nuevas en su propio filesystem:
`comun/` (carpeta hermana de `relay/`, con `parseo_sensores.py`) y
[`relay/leer_companero.py`](relay/leer_companero.py). Esto es lo que el backend central invoca
por SSH (`exec_command`) para pedirle al gateway que lea a su compañero — el backend central
**nunca** ve las credenciales de `companeros.yaml`.

Hay dos formas de hacerlo llegar — **elige según si el gateway tiene salida a internet/GitHub**:

**Opción 1 — clonar el repo completo con git** (más simple de mantener actualizado después,
`git pull` cada vez que algo cambie):

```bash
cd /home/<usuario>
git clone https://github.com/imedina27/monit_servers.git monit_servers_v2
```

> Si alguna vez corriste algo con `sudo git` ahí dentro, `git pull` puede fallar después con
> `insufficient permission for adding an object to repository database` — eso es un problema de
> dueño de archivos en `.git/`, no de git en sí. Arréglalo con
> `sudo chown -R <usuario>:<usuario> <ruta_repo>/.git` y vuelve a intentar.

**Opción 2 — copiar solo los archivos sueltos por `scp`** (sin git; es lo que usan hoy los
2 gateways reales de producción, `apiman-fase1` y `quantumdata` — sus archivos se subieron a
mano, no por clon de git):

```bash
# Desde una maquina que SI tenga el repo (ej. DEVELOP), hacia el gateway nuevo:
scp -r comun quantum@<ip_gateway>:/home/<usuario>/monit_servers_v2/
scp relay/leer_companero.py quantum@<ip_gateway>:/home/<usuario>/monit_servers_v2/relay/
```

(si el gateway es completamente nuevo y todavía no tiene ni `relay.py`, copia también
`relay/relay.py`, `relay/config.ini` y `relay/monit_servers_v2_relay.service` en el mismo paso,
antes de C.2).

No hace falta reiniciar ningún servicio en ninguna de las dos opciones — `leer_companero.py` no
es un proceso persistente, se ejecuta fresco cada vez que DEVELOP lo invoca por SSH.

### C.5 Agregar `ruta_repo` al gateway (obligatorio para Tiempo Real)

En el inventario central, agrega a la entrada del gateway (junto a `es_gateway_de`) la ruta
ABSOLUTA del repo **en esa misma máquina gateway** (no en DEVELOP) — donde quedó
`relay/leer_companero.py` en el paso anterior:

```yaml
    es_gateway_de: [<companero_1>, <companero_2>]
    ruta_repo: /home/<usuario>/monit_servers_v2
```

Es un campo **obligatorio y explícito a propósito** (`backend/ssh_lectura_directa.py` nunca lo
adivina) — sin él, Tiempo Real queda deshabilitado para los compañeros de ese gateway con un
mensaje claro, en vez de intentar una ruta equivocada en silencio.

### C.6 Verificar

```bash
curl -s http://192.168.192.205:8000/api/servidores/<companero_1>/tiempo_real/disponible
# {"disponible":true,"motivo":null}
curl -s http://192.168.192.205:8000/api/servidores/<companero_1>/tiempo_real/lectura
# [{"componente":"cpu","sensor":"...","temperatura_c":...,"medido_en":"...","estado":"verde"}, ...]
```

Si falla, el mensaje de error distingue si fue el gateway el que no contestó (red/SSH) o el
compañero en particular (ver `LecturaNoDisponible` en `backend/ssh_lectura_directa.py`) —
nunca debería salir un traceback crudo en la respuesta.

Continúa en [Hardware y umbrales](#hardware-y-umbrales-las-4-variantes).

---

## Variante D — 100% offline (sin gateway, sin ninguna ruta de red)

Para un sitio tipo AbInBev: ni el servidor ni nada en su LAN es alcanzable desde DEVELOP, la
única forma de traer datos es físicamente (USB, visita al sitio).

### D.1 Instalar el colector

Igual que la Parte 0.

### D.2 Alta en el inventario central

```yaml
  - nombre: <NOMBRE_SERVIDOR>
    grupo: <Cliente>/<Sitio>
    sistema_operativo: ubuntu
    activo: false
    ip:
    puerto:
    usuario:
    password:
    directorio_remoto: /home/<usuario>/monit_servers_v2/colector_ubuntu/lecturas
```

Sin `es_gateway_de` ni `directorio_relay` — este servidor no es gateway de nadie. Si en el
mismo sitio hay varios servidores que se ven entre sí mediante un "hub" (uno de ellos corre su
propio `relay.py` para recolectar a los demás, aunque el hub mismo tampoco sea alcanzable desde
DEVELOP), sigue la Variante C para instalar el relay ahí, pero con el hub también en
`activo: false` (ver la fila "Sitio 100% offline con un hub" en el README) — la diferencia con
un gateway online es solo esa bandera, el `relay.py` es idéntico.

### D.3 Carga manual de datos

Dos formas:

- **Servidor suelto**: copia los `.csv` generados por el colector a
  `ingesta/pendientes_offline/<NOMBRE_SERVIDOR>/` en DEVELOP (por USB, SFTP manual, lo que esté
  disponible), y dispara la ingesta (`curl -X POST .../api/ingesta/ejecutar`). También puedes
  usar [`scripts/cargar_offline_remoto.py`](scripts/cargar_offline_remoto.py) desde tu propia
  máquina si tienes los `.csv` ahí — sube por SFTP y dispara la ingesta en un solo paso
  (variables `DEVELOP_*` de `.env.example`).

- **Sitio completo con hub** (varios servidores): en el hub, corre
  [`relay/empaquetar_offline.py`](relay/empaquetar_offline.py) — arma un `.zip` con una
  subcarpeta por servidor (el hub + cada compañero), verifica su integridad, y solo borra los
  `.csv` originales tras confirmar. Ya en DEVELOP, deja ese `.zip` en `relay/zips/` y corre
  [`scripts/desempaquetar_offline.py`](scripts/desempaquetar_offline.py) — sube cada subcarpeta
  y dispara la ingesta, sin descomprimir ni copiar nada a mano.

### D.4 "Tiempo Real" — nunca va a estar disponible aquí

No hay ninguna ruta SSH posible (ni directa ni vía gateway alcanzable), así que
`backend/ssh_lectura_directa.py` siempre va a resolver este servidor como "sin ruta" y el botón
queda deshabilitado en el dashboard. No es un bug ni algo pendiente de configurar — es
físicamente correcto para este tipo de sitio. Confírmalo si quieres:

```bash
curl -s http://192.168.192.205:8000/api/servidores/<NOMBRE_SERVIDOR>/tiempo_real/disponible
# {"disponible":false,"motivo":"Este servidor no tiene una ruta SSH directa ni es companero de un gateway activo."}
```

---

## Hardware y umbrales (las 4 variantes)

Opcional pero recomendado — llena la ficha técnica de hardware y los umbrales específicos del
dashboard. Se hace UNA sola vez por servidor (o de nuevo si cambia el hardware físico).

### Extraer el hardware real

[`scripts/extraer_hardware.py`](scripts/extraer_hardware.py) se corre **en el servidor Linux**
(no en la máquina central), es de solo lectura, no instala nada:

```bash
sudo python3 extraer_hardware.py
```

Genera `<hostname>.json` en el directorio actual (el hostname real vía
`socket.gethostname()` — debe coincidir, sin importar mayúsculas/minúsculas, con el `nombre`
del inventario; si no coincide, edita el campo `"hostname"` del `.json` a mano antes de
importar). Sin `sudo` corre igual, pero sin el detalle de DIMMs ni el número de serie del
chasis (requieren `dmidecode` con root) — el script avisa cuando pasa esto.

Descarga el `.json` a tu máquina (scp/SFTP). Si se corrió con `sudo`, puede quedar como dueño
`root` — corrige con `sudo chown <tu_usuario>:<tu_usuario> <hostname>.json` antes de bajarlo si
tu cliente de SFTP se queja de permisos.

### Importarlo a Postgres (vía Docker, en DEVELOP)

El puerto de Postgres en DEVELOP no está expuesto a la red, así que esto se corre **dentro**
del contenedor del backend (que ya tiene `DB_HOST=postgres` configurado):

```bash
docker cp /opt/quantum/monit-servers-v2/db/gestionar_servidor.py \
    monit-servers-v2-backend:/tmp/gestionar_servidor.py

docker cp <hostname>.json monit-servers-v2-backend:/tmp/<hostname>.json

cd /opt/quantum/monit-servers-v2/docker
docker compose exec backend python /tmp/gestionar_servidor.py importar /tmp/<hostname>.json
```

Si da "No existe ningún servidor que coincida con el hostname...": revisa que el `nombre` del
inventario coincida con el hostname real del servidor, y que ya hayas disparado la ingesta al
menos una vez (el servidor debe existir ya en la tabla `servidores`).

### Umbrales de temperatura (opcional)

Sin esto, el servidor usa el default genérico (CPU 70/85°C, GPU 75/85°C en `backend/main.py`).
Para poner un umbral propio (recomendado si investigaste el TCASE/Tjmax real):

```bash
docker compose exec backend python /tmp/gestionar_servidor.py umbrales <NOMBRE_SERVIDOR>
```

Interactivo, pide 4 valores en orden (Enter en blanco deja el default genérico para ese
componente): `CPU verde_max`, `CPU ambar_max`, `GPU verde_max`, `GPU ambar_max`.

---

## Checklist final de verificación

- [ ] El servicio `monit_servers_v2` está `active (running)` en el servidor nuevo
      (`sudo systemctl status monit_servers_v2`).
- [ ] (Variantes B/C) El servicio `monit_servers_v2_relay` está `active (running)` en el
      gateway, y `relay.log` muestra recolección exitosa del compañero nuevo.
- [ ] El servidor aparece en el árbol del dashboard, dentro del grupo correcto.
- [ ] "Estado actual" muestra temperaturas reales (no `--°C`).
- [ ] La sección de "Uso de disco" muestra los puntos de montaje reales.
- [ ] (Si hiciste hardware) La ficha de hardware debajo de "Todos los sensores" muestra datos
      reales.
- [ ] (Si hiciste umbrales) El semáforo usa los umbrales específicos, no el genérico.
- [ ] El botón "Tiempo Real" aparece **habilitado** (Variantes A/B/C) o **deshabilitado**
      (Variante D) según corresponda — confirmado con
      `GET /api/servidores/<nombre>/tiempo_real/disponible`.

## Dar de baja un servidor

Si una alta quedó mal hecha o el servidor se retira definitivamente:

```bash
docker compose exec backend python /tmp/gestionar_servidor.py baja <NOMBRE_SERVIDOR>
```

Pide confirmación explícita (escribir `si`), borra lecturas/uso de disco/hardware/umbrales en
el orden correcto, y limpia los grupos del árbol que queden vacíos. **Solo toca Postgres** —
recuerda quitar también la entrada de `inventario_servidores.yaml` (y, si era un compañero, del
`es_gateway_de` del gateway y de su `companeros.yaml`) si es un retiro definitivo.
