"""
Lectura de temperatura "en vivo" (CPU/GPU) bajo demanda, para el boton
"Tiempo Real" del dashboard -- a diferencia de ingesta/ingesta.py (SFTP de
archivos por lotes), aqui se abre una sesion SSH puntual y se ejecuta
'sensors'/'nvidia-smi' directo en el servidor (exec_command), sin pasar por
el colector ni por la base de datos.

Tres casos por servidor (ver inventario_servidores.yaml):
  - "directo": el servidor tiene 'activo: true' en el inventario -- se abre
    SSH directo con esas credenciales.
  - "companero": el servidor aparece en el 'es_gateway_de' de otro servidor
    (un gateway) -- el backend central NUNCA tiene las credenciales del
    companero (viven solo en relay/companeros.yaml, en el propio gateway).
    En vez de eso, le pide al gateway (por SSH + exec_command) que el mismo
    lea a su companero y regrese el resultado (relay/leer_companero.py).
    Requiere que ese gateway tenga 'ruta_repo' en inventario_servidores.yaml
    (ruta absoluta del repo EN ESA MAQUINA, ej. /home/quantum/monit_servers_v2)
    -- es obligatorio y explicito a proposito, nunca se adivina.
  - "no_disponible": ni lo uno ni lo otro (ej. sitios 100% offline sin
    gateway, como AbInBev) -- no hay ninguna ruta SSH posible.

No se persiste nada en la base de datos -- estas lecturas son efimeras.
"""
import json
import os
import shlex
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko
import yaml

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

# comun/ vive en la raiz del repo, no junto a este archivo -- hay que
# asegurarse de que este en sys.path antes de importarlo.
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from comun import parseo_sensores  # noqa: E402

TIEMPO_INACTIVIDAD_SESION_SEG = 60
TIEMPO_CACHE_LECTURA_SEG = 2

_lock = threading.Lock()
_sesiones = {}  # clave -> {"cliente": SSHClient, "ultimo_uso": float}
_cache_lecturas = {}  # clave -> (timestamp, resultado)


class LecturaNoDisponible(Exception):
    """No se pudo obtener una lectura en vivo -- ni por falta de ruta SSH
    (servidor 100% offline sin gateway) ni por falla de conexion puntual
    (red caida, host apagado, etc). El llamador (backend/main.py) la traduce
    a un 503 con mensaje claro, nunca debe propagarse como un 500 crudo."""


def _cargar_inventario():
    """
    Copia deliberada (no importa ingesta.cargar_inventario()) para no tocar
    ingesta/ingesta.py -- este modulo es nuevo y no debe modificar nada ya
    desplegado en produccion. INVENTARIO_PATH es solo para pruebas en
    sandbox; sin esa variable de entorno, lee exactamente el mismo archivo
    que usa la ingesta real.
    """
    ruta = os.environ.get("INVENTARIO_PATH") or str(PROJECT_DIR / "inventario_servidores.yaml")
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f)
    return {s["nombre"]: s for s in datos["servidores"]}


def _resolver_caso(nombre_servidor, inventario):
    """
    Devuelve (caso, info, motivo) -- 'motivo' solo viene lleno para
    "no_disponible", explicando exactamente por que (sirve tal cual para el
    mensaje que ve el usuario en el boton "Tiempo Real" del dashboard).
    """
    servidor = inventario.get(nombre_servidor)
    if servidor and servidor.get("activo"):
        return "directo", servidor, None

    for nombre_posible_gateway, datos in inventario.items():
        if nombre_servidor not in (datos.get("es_gateway_de") or []):
            continue

        if not datos.get("activo"):
            return "no_disponible", None, (
                f"El gateway '{nombre_posible_gateway}' de este servidor no esta activo."
            )
        if not datos.get("ruta_repo"):
            return "no_disponible", None, (
                f"El gateway '{nombre_posible_gateway}' no tiene 'ruta_repo' configurado en "
                "inventario_servidores.yaml -- agregalo (ruta absoluta del repo en ESE gateway, "
                "ver relay/leer_companero.py) para habilitar Tiempo Real en sus companeros."
            )
        return "companero", (nombre_posible_gateway, datos), None

    return "no_disponible", None, (
        "Este servidor no tiene una ruta SSH directa ni es companero de un gateway activo."
    )


def disponibilidad(nombre_servidor):
    inventario = _cargar_inventario()
    caso, _, motivo = _resolver_caso(nombre_servidor, inventario)
    if caso == "no_disponible":
        return False, motivo
    return True, None


def obtener_lectura(nombre_servidor):
    inventario = _cargar_inventario()
    caso, info, motivo = _resolver_caso(nombre_servidor, inventario)

    if caso == "directo":
        return _leer_directo(nombre_servidor, info)
    if caso == "companero":
        nombre_gateway, gateway_info = info
        return _leer_companero(nombre_servidor, nombre_gateway, gateway_info)

    raise LecturaNoDisponible(motivo)


# ─── Conexion SSH y ejecucion de comandos ─────────────────────────────────────
def _conectar(host_info, etiqueta):
    cliente = paramiko.SSHClient()
    cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        cliente.connect(
            hostname=host_info["ip"],
            port=host_info.get("puerto", 22),
            username=host_info["usuario"],
            password=host_info.get("password") or None,
            timeout=15,
        )
    except (OSError, paramiko.SSHException) as e:
        raise LecturaNoDisponible(f"no se pudo conectar a '{etiqueta}' por SSH: {e}") from e
    return cliente


def _ejecutar(cliente, comando, timeout=10):
    _, stdout, stderr = cliente.exec_command(comando, timeout=timeout)
    salida = stdout.read().decode("utf-8", errors="replace").strip()
    error = stderr.read().decode("utf-8", errors="replace").strip()
    return salida, error


def _leer_cpu_gpu(cliente):
    salida_sensors, _ = _ejecutar(cliente, f"{parseo_sensores.COMANDO_WHICH_SENSORS} && {parseo_sensores.COMANDO_SENSORS}")
    cpu = parseo_sensores.parsear_cpu_sensors(salida_sensors) if salida_sensors else {}
    if not cpu:
        salida_thermal, _ = _ejecutar(cliente, parseo_sensores.COMANDO_THERMAL_ZONES_SSH)
        cpu = parseo_sensores.parsear_cpu_thermal_zones_ssh(salida_thermal)

    salida_which_gpu, _ = _ejecutar(cliente, parseo_sensores.COMANDO_WHICH_NVIDIA_SMI)
    gpu = {}
    if salida_which_gpu:
        salida_gpu, _ = _ejecutar(cliente, parseo_sensores.COMANDO_NVIDIA_SMI)
        gpu = parseo_sensores.parsear_gpu(salida_gpu)

    return cpu, gpu


def _empaquetar(cpu, gpu, medido_en=None):
    medido_en = medido_en or datetime.now(timezone.utc).isoformat()
    filas = [{"componente": "cpu", "sensor": sensor, "temperatura_c": valor, "medido_en": medido_en}
              for sensor, valor in cpu.items()]
    filas += [{"componente": "gpu", "sensor": sensor, "temperatura_c": valor, "medido_en": medido_en}
              for sensor, valor in gpu.items()]
    return filas


# ─── Pool de sesiones SSH (reusadas mientras "Tiempo Real" este activo) ───────
def _cerrar_inactivas():
    ahora = time.time()
    with _lock:
        inactivas = [clave for clave, e in _sesiones.items() if ahora - e["ultimo_uso"] > TIEMPO_INACTIVIDAD_SESION_SEG]
        for clave in inactivas:
            try:
                _sesiones[clave]["cliente"].close()
            except Exception:
                pass
            del _sesiones[clave]


def _obtener_sesion(clave, host_info, etiqueta):
    with _lock:
        entrada = _sesiones.get(clave)
        if entrada is not None:
            transport = entrada["cliente"].get_transport()
            if transport is not None and transport.is_active():
                entrada["ultimo_uso"] = time.time()
                return entrada["cliente"]
            try:
                entrada["cliente"].close()
            except Exception:
                pass
            del _sesiones[clave]

    # Conectar fuera del lock -- puede tardar hasta el timeout de 15s, no
    # queremos bloquear lecturas de otros servidores mientras tanto.
    cliente = _conectar(host_info, etiqueta)
    with _lock:
        _sesiones[clave] = {"cliente": cliente, "ultimo_uso": time.time()}
    return cliente


def _descartar_sesion(clave):
    with _lock:
        entrada = _sesiones.pop(clave, None)
    if entrada is not None:
        try:
            entrada["cliente"].close()
        except Exception:
            pass


# ─── Cache anti-rafaga (ej. dos pestañas con Tiempo Real activo a la vez) ─────
def _revisar_cache(clave):
    entrada = _cache_lecturas.get(clave)
    if entrada is not None and time.time() - entrada[0] < TIEMPO_CACHE_LECTURA_SEG:
        return entrada[1]
    return None


def _guardar_cache(clave, resultado):
    _cache_lecturas[clave] = (time.time(), resultado)


# ─── Caso 1: servidor directo ──────────────────────────────────────────────────
def _leer_directo(nombre, host_info):
    _cerrar_inactivas()
    clave = f"directo:{nombre}"

    cacheado = _revisar_cache(clave)
    if cacheado is not None:
        return cacheado

    cliente = _obtener_sesion(clave, host_info, nombre)
    try:
        cpu, gpu = _leer_cpu_gpu(cliente)
    except Exception as e:
        _descartar_sesion(clave)
        raise LecturaNoDisponible(f"error leyendo '{nombre}': {e}") from e

    resultado = _empaquetar(cpu, gpu)
    _guardar_cache(clave, resultado)
    return resultado


# ─── Caso 2: companero detras de un gateway (delegado) ─────────────────────────
def _leer_companero(nombre, nombre_gateway, gateway_info):
    _cerrar_inactivas()
    clave_cache = f"companero:{nombre}"

    cacheado = _revisar_cache(clave_cache)
    if cacheado is not None:
        return cacheado

    clave_sesion = f"gateway:{nombre_gateway}"
    cliente = _obtener_sesion(clave_sesion, gateway_info, nombre_gateway)

    # 'ruta_repo' es obligatorio y ya viene validado por _resolver_caso() --
    # nunca se adivina/deduce, para no apuntar a una ruta equivocada en
    # silencio si algun gateway personalizo su propio layout.
    ruta_repo = gateway_info["ruta_repo"]
    comando = f"python3 {shlex.quote(ruta_repo + '/relay/leer_companero.py')} {shlex.quote(nombre)}"

    try:
        salida, error = _ejecutar(cliente, comando, timeout=20)
    except Exception as e:
        _descartar_sesion(clave_sesion)
        raise LecturaNoDisponible(f"no se pudo contactar al gateway '{nombre_gateway}': {e}") from e

    if not salida:
        raise LecturaNoDisponible(
            error or f"'{nombre_gateway}' no devolvio ninguna lectura para '{nombre}'."
        )

    try:
        datos = json.loads(salida)
    except json.JSONDecodeError as e:
        raise LecturaNoDisponible(f"respuesta invalida de '{nombre_gateway}' para '{nombre}': {e}") from e

    resultado = _empaquetar(datos.get("cpu", {}), datos.get("gpu", {}), medido_en=datos.get("medido_en"))
    _guardar_cache(clave_cache, resultado)
    return resultado
