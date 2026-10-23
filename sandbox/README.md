# Sandbox de "Tiempo Real"

Entorno de prueba para la funcionalidad de polling SSH en vivo (ver
`backend/ssh_lectura_directa.py`, `relay/leer_companero.py`). Replica los 3
casos posibles -- **nunca toca** `inventario_servidores.yaml`,
`relay/companeros.yaml` ni ningún servidor real.

Hay dos formas de levantarlo. **Ninguna de las dos requiere tocar nada de
produccion**; usa la que tengas disponible.

## Opcion A (recomendada aqui): sin Docker, solo Python + paramiko

No necesita Docker ni WSL -- `sandbox/servidor_falso.py` es un servidor SSH
real (modo servidor de `paramiko`, que el proyecto ya trae como
dependencia) corriendo en puro Python, respondiendo a los mismos comandos
que usa `ssh_lectura_directa.py`/`leer_companero.py` con datos de ejemplo.
`sandbox/levantar_sandbox.py` levanta los 3 "servidores" (puertos
2202/2203/2204 en `127.0.0.1`) en un solo proceso, y el "gateway" (2202)
corre `relay/leer_companero.py` **de verdad** (no un stub) para delegarle la
lectura al "companero" (2204) exactamente como lo haria un gateway real.

```
python sandbox/levantar_sandbox.py
```

Déjalo corriendo en una terminal aparte (Ctrl+C para apagar). Ya validado
(2026-10-23) end-to-end: caso directo, caso companero-vía-gateway (con la
delegacion real), y el caso de falla limpia (servidor apagado -> excepcion
clara, no traceback).

### Probar `ssh_lectura_directa.py` directo (sin FastAPI ni Postgres)

Con el sandbox corriendo, en OTRA terminal, desde la raíz del repo:

```
INVENTARIO_PATH=sandbox/inventario_servidores.sandbox.yaml python -c "
import sys; sys.path.insert(0, 'backend')
import ssh_lectura_directa as t
print('directo:', t.obtener_lectura('sandbox_directo'))
print('companero:', t.obtener_lectura('sandbox_companero'))
print('disponible sin_ruta:', t.disponibilidad('sandbox_sin_ruta'))
"
```

Para ver el caso de falla limpia: apaga el sandbox (Ctrl+C en su terminal) y
repite la llamada -- debe salir `LecturaNoDisponible` con mensaje claro, no
un traceback crudo.

## Opcion B: con Docker (si lo tienes disponible)

`sandbox/docker-compose.yml` + `Dockerfile.servidor`/`Dockerfile.gateway`
hacen lo mismo con 3 contenedores Linux reales en vez de servidores SSH
simulados en Python -- mas fiel a produccion (sensors/nvidia-smi corren de
verdad como binarios, aunque con salida falsa), pero no se pudo validar en
esta maquina por no tener Docker instalado.

```
cd sandbox
docker compose up -d --build
```

Contenedores: `sandbox-directo` (puerto `2203`), `sandbox-gateway` (puerto
`2202`, con un companero), `sandbox-companero` (sin puerto expuesto al host
-- a propósito, igual que un companero real).

```
ssh monitor@127.0.0.1 -p 2203   # sandbox-directo, password: monitor
ssh monitor@127.0.0.1 -p 2202   # sandbox-gateway, password: monitor
```

Para el caso de falla: `docker compose stop sandbox-companero` y repetir la
prueba de `ssh_lectura_directa.py` de arriba.

```
cd sandbox
docker compose down
```

## Probar el flujo completo (backend + dashboard), con cualquiera de las dos opciones

Requiere ademas que `sandbox_directo`/`sandbox_gateway`/`sandbox_companero`
existan como filas en la tabla `servidores` de tu Postgres de desarrollo
(los endpoints `/tiempo_real/*` consultan umbrales ahi, igual que `/actual`)
-- usa `db/gestionar_servidor.py` o un INSERT manual para un servidor de
prueba, igual que para cualquier servidor nuevo.

Con eso ya cargado, corre el backend apuntando al inventario del sandbox:

```
INVENTARIO_PATH=sandbox/inventario_servidores.sandbox.yaml uvicorn main:app --reload --app-dir backend
```

Y abre el dashboard, selecciona `sandbox_directo` o `sandbox_gateway` en el
árbol, y prueba el botón "Tiempo Real".
