"""
Sube un bundle de lecturas offline (.csv de colector_ubuntu/relay) directo a
DEVELOP por SFTP y dispara la ingesta, sin tener que entrar por SSH a mano.

Uso: python scripts/cargar_offline_remoto.py <nombre_servidor> <carpeta_con_csv>

<nombre_servidor> debe coincidir con el 'nombre' en inventario_servidores.yaml
(y con el nombre de carpeta que ya usa el flujo offline normal, ver paso 11
del ROADMAP). <carpeta_con_csv> es la carpeta local donde ya copiaste a mano
los .csv del servidor/relay (ej. un USB, una copia por SSH, etc.).

Requiere en .env: DEVELOP_HOST, DEVELOP_SSH_PORT (opcional, 22 por defecto),
DEVELOP_SSH_USER, DEVELOP_SSH_PASSWORD, DEVELOP_REMOTE_PATH, DEVELOP_API_URL.
Ver .env.example.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import paramiko
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")


class DevelopNoDisponible(Exception):
    """DEVELOP no se pudo conectar por SSH (red caida, host apagado, timeout,
    credenciales invalidas, etc.) -- distinto de un error de un bundle/zip en
    particular, afecta a cualquier intento de subida mientras persista."""


def subir_bundle(carpeta_local, nombre_servidor):
    cliente = paramiko.SSHClient()
    cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        cliente.connect(
            hostname=os.environ["DEVELOP_HOST"],
            port=int(os.environ.get("DEVELOP_SSH_PORT", "22")),
            username=os.environ["DEVELOP_SSH_USER"],
            password=os.environ["DEVELOP_SSH_PASSWORD"],
            timeout=15,
        )
    except (OSError, paramiko.SSHException) as e:
        raise DevelopNoDisponible(f"no se pudo conectar a DEVELOP por SSH: {e}") from e
    sftp = cliente.open_sftp()

    remoto_servidor = f"{os.environ['DEVELOP_REMOTE_PATH']}/{nombre_servidor}"
    try:
        sftp.mkdir(remoto_servidor)
    except IOError:
        pass  # ya existe

    archivos = sorted(Path(carpeta_local).glob("*.csv"))
    for archivo in archivos:
        sftp.put(str(archivo), f"{remoto_servidor}/{archivo.name}")
        print(f"  Subido: {archivo.name}")

    sftp.close()
    cliente.close()
    return len(archivos)


def disparar_ingesta():
    url = os.environ["DEVELOP_API_URL"].rstrip("/") + "/api/ingesta/ejecutar"
    peticion = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(peticion, timeout=180) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def main():
    if len(sys.argv) != 3:
        print(f"Uso: python {sys.argv[0]} <nombre_servidor> <carpeta_con_csv>", file=sys.stderr)
        sys.exit(1)

    nombre_servidor, carpeta_local = sys.argv[1], sys.argv[2]
    if not Path(carpeta_local).is_dir():
        print(f"Error: '{carpeta_local}' no es una carpeta valida.", file=sys.stderr)
        sys.exit(1)

    print(f"Subiendo bundle de '{nombre_servidor}' desde {carpeta_local} a DEVELOP...")
    try:
        n_subidos = subir_bundle(carpeta_local, nombre_servidor)
    except DevelopNoDisponible as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Nada se subio -- intenta de nuevo cuando DEVELOP este disponible.", file=sys.stderr)
        sys.exit(1)
    if n_subidos == 0:
        print("No se encontraron archivos .csv en esa carpeta, nada que subir.")
        return
    print(f"{n_subidos} archivo(s) subido(s). Disparando ingesta en DEVELOP...")

    try:
        resultado = disparar_ingesta()
    except urllib.error.URLError as e:
        print(f"Error al llamar la ingesta: {e}", file=sys.stderr)
        print("Los archivos ya quedaron subidos -- se cargaran en la siguiente ingesta normal.")
        sys.exit(1)

    print(
        f"Ingesta completada: {resultado['online_cargados']} online cargados, "
        f"{resultado['online_omitidos']} ya estaban cargados, "
        f"{resultado['offline_cargados']} offline cargados."
    )


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        sys.exit(1)
