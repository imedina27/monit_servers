import os
import time
import configparser
import logging

import yaml
import paramiko

# ─── Configuracion del log ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "relay.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


# ─── Lectura de configuracion ─────────────────────────────────────────────────
def cargar_configuracion():
    config = configparser.ConfigParser()
    config_path = os.path.join(BASE_DIR, "config.ini")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"No se encontro el archivo de configuracion: {config_path}")
    config.read(config_path, encoding="utf-8")
    return config


def cargar_companeros():
    """
    companeros.yaml vive solo en este servidor (gitignored) -- nunca en el
    inventario central ni en git, porque sus credenciales son propias de
    este sitio. Ver companeros.yaml.example para el formato.
    """
    ruta = os.path.join(BASE_DIR, "companeros.yaml")
    if not os.path.exists(ruta):
        raise FileNotFoundError(
            f"No se encontro {ruta}. Copia 'companeros.yaml.example' a 'companeros.yaml' "
            f"y completa los datos reales de este sitio."
        )
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f) or {}
    return datos.get("companeros", [])


# ─── Recoleccion de un companero ──────────────────────────────────────────────
def procesar_companero(companero, directorio_entrante):
    """
    Se conecta por SSH/SFTP al companero, descarga cada .csv pendiente a
    'directorio_entrante/<nombre_companero>/', y solo borra del companero los
    archivos que ya quedaron escritos en disco localmente -- mismo criterio
    idempotente que ya usa ingesta.py (nunca se pierde un archivo a medio
    camino). La descarga se hace a un '.tmp' y se renombra al final, para que
    un corte a medio archivo nunca deje un '.csv' local incompleto.
    """
    nombre = companero["nombre"]
    carpeta_local = os.path.join(directorio_entrante, nombre)
    os.makedirs(carpeta_local, exist_ok=True)

    cliente = paramiko.SSHClient()
    cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cliente.connect(
        hostname=companero["ip"],
        port=companero.get("puerto", 22),
        username=companero["usuario"],
        # Si 'password' viene vacio (sitios con llave SSH, ej. AbInBev),
        # paramiko intenta la llave por defecto / el agente SSH automaticamente.
        password=companero.get("password") or None,
        timeout=15,
    )
    sftp = cliente.open_sftp()
    recolectados = 0
    try:
        try:
            archivos = sorted(f for f in sftp.listdir(companero["directorio_remoto"]) if f.endswith(".csv"))
        except FileNotFoundError:
            logging.warning(f"[{nombre}] Directorio remoto no existe: {companero['directorio_remoto']}")
            archivos = []

        for nombre_archivo in archivos:
            ruta_remota = f"{companero['directorio_remoto']}/{nombre_archivo}"
            ruta_local = os.path.join(carpeta_local, nombre_archivo)
            ruta_local_tmp = ruta_local + ".tmp"

            if not os.path.exists(ruta_local):
                sftp.get(ruta_remota, ruta_local_tmp)
                os.replace(ruta_local_tmp, ruta_local)
            # Si ruta_local ya existe, es que en una corrida anterior se
            # descargo bien pero fallo el borrado -- solo se reintenta borrar.

            try:
                sftp.remove(ruta_remota)
                recolectados += 1
                logging.info(f"[{nombre}] Recolectado: {nombre_archivo}")
            except Exception as e:
                logging.warning(f"[{nombre}] Descargado pero no se pudo borrar {nombre_archivo} del companero: {e}")
    finally:
        sftp.close()
        cliente.close()

    return recolectados


# ─── Ciclo principal ──────────────────────────────────────────────────────────
def main():
    logging.info("=== Iniciando relay ===")

    config = cargar_configuracion()
    intervalo_min = int(config["relay"]["intervalo_minutos"])
    directorio_entrante = os.path.join(BASE_DIR, config["almacenamiento"]["directorio_entrante"])
    intervalo_seg = intervalo_min * 60

    while True:
        try:
            companeros = cargar_companeros()
            if not companeros:
                logging.warning("No hay companeros configurados en companeros.yaml")

            for companero in companeros:
                nombre = companero["nombre"]
                try:
                    n = procesar_companero(companero, directorio_entrante)
                    logging.info(f"[{nombre}] {n} archivo(s) recolectado(s) en este ciclo.")
                except Exception as e:
                    logging.error(f"[{nombre}] Error en la recoleccion: {e}")

        except Exception as e:
            logging.error(f"Error durante el ciclo de relay: {e}")

        logging.info(f"Proximo ciclo de relay en {intervalo_min} minutos.")
        time.sleep(intervalo_seg)


if __name__ == "__main__":
    main()
