"""
Script puntual que vive en cada gateway, para el boton "Tiempo Real" del
dashboard: el backend central le pide a ESTE gateway, por SSH + exec_command,
que lea la temperatura de UNO de sus companeros usando las credenciales que
ya tiene en relay/companeros.yaml -- el backend central nunca ve esas
credenciales (ver paso de diseno "Tiempo Real", decision de delegar en el
gateway en vez de centralizarlas).

No modifica relay.py ni su servicio systemd -- es un script aparte, de
ejecucion puntual bajo demanda, no un proceso persistente.

Uso: python3 leer_companero.py <nombre_companero>

Imprime a stdout un JSON {"cpu": {...}, "gpu": {...}, "medido_en": "..."} y
termina con exit code 0. Si algo falla, imprime el error a stderr y termina
con exit code 1 -- asi el backend central distingue "este companero fallo"
de un crash sin mensaje (mismo criterio que DevelopNoDisponible en
scripts/cargar_offline_remoto.py).
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import paramiko
import yaml

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from comun import parseo_sensores  # noqa: E402


def _cargar_companeros():
    """
    Copia deliberada de relay.py:cargar_companeros() -- no se importa
    relay.py directo para no arrastrar su logging.basicConfig (pensado para
    el servicio persistente, no para un script puntual) ni acoplar este
    script al loop de relay.py.
    """
    ruta = os.environ.get("COMPANEROS_PATH") or str(BASE_DIR / "companeros.yaml")
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"No se encontro {ruta}.")
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f) or {}
    return {c["nombre"]: c for c in datos.get("companeros", [])}


def _conectar(companero):
    cliente = paramiko.SSHClient()
    cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cliente.connect(
        hostname=companero["ip"],
        port=companero.get("puerto", 22),
        username=companero["usuario"],
        password=companero.get("password") or None,
        timeout=15,
    )
    return cliente


def _ejecutar(cliente, comando, timeout=10):
    _, stdout, stderr = cliente.exec_command(comando, timeout=timeout)
    salida = stdout.read().decode("utf-8", errors="replace").strip()
    error = stderr.read().decode("utf-8", errors="replace").strip()
    return salida, error


def leer_companero(nombre_companero):
    companeros = _cargar_companeros()
    companero = companeros.get(nombre_companero)
    if companero is None:
        raise RuntimeError(f"'{nombre_companero}' no esta en companeros.yaml de este gateway")

    cliente = _conectar(companero)
    try:
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
    finally:
        cliente.close()

    return {
        "cpu": cpu,
        "gpu": gpu,
        "medido_en": datetime.now(timezone.utc).isoformat(),
    }


def main():
    if len(sys.argv) != 2:
        print(f"Uso: python3 {sys.argv[0]} <nombre_companero>", file=sys.stderr)
        sys.exit(1)

    try:
        resultado = leer_companero(sys.argv[1])
    except Exception as e:
        print(f"Error leyendo companero '{sys.argv[1]}': {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(resultado))


if __name__ == "__main__":
    main()
