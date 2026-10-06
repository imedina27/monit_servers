import csv
import os
import re
import shutil
import time
import configparser
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# ─── Configuracion del log ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "monitor.log")

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

# ─── Ejecutar comando local ───────────────────────────────────────────────────
def ejecutar_comando(comando):
    resultado = subprocess.run(
        comando,
        shell=True,
        capture_output=True,
        text=True
    )
    if resultado.returncode != 0:
        logging.warning(f"Error en comando '{comando}': {resultado.stderr.strip()}")
    return resultado.stdout.strip()

# ─── Detectar metodo de lectura de CPU ───────────────────────────────────────
def detectar_metodo_cpu():
    """
    Detecta automaticamente si usar lm-sensors o thermal zones.
    Retorna 'sensors' o 'thermal_zones'.
    """
    resultado = ejecutar_comando("which sensors")
    if resultado:
        # Verificar que sensors devuelve datos utiles (cualquier chip, no solo
        # coretemp de Intel -- ver parsear_cpu_sensors)
        salida = ejecutar_comando("sensors")
        if parsear_cpu_sensors(salida):
            logging.info("Metodo CPU detectado: lm-sensors")
            return "sensors"

    # Verificar thermal zones como alternativa (no cooling_device, que no trae temperatura)
    thermal_path = Path("/sys/class/thermal")
    if thermal_path.exists() and any(thermal_path.glob("thermal_zone*")):
        logging.info("Metodo CPU detectado: thermal_zones")
        return "thermal_zones"

    logging.warning("No se encontro metodo de lectura de CPU")
    return None

# ─── Detectar si hay GPU disponible ──────────────────────────────────────────
def detectar_gpu():
    """
    Detecta si nvidia-smi esta disponible y devuelve datos.
    Retorna True o False.
    """
    resultado = ejecutar_comando("which nvidia-smi")
    if resultado:
        salida = ejecutar_comando(
            "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits"
        )
        if salida:
            logging.info("GPU detectada: nvidia-smi disponible")
            return True
    logging.info("GPU no detectada: nvidia-smi no disponible")
    return False

# ─── Parsear temperaturas CPU via lm-sensors ─────────────────────────────────
def parsear_cpu_sensors(salida_sensors):
    """
    No filtra por nombre de etiqueta (Core/Package son de Intel/coretemp;
    otros chips como k10temp de AMD usan Tctl/Tccd, y habria mas nombres
    segun el fabricante). En vez de eso, valida que el valor termine en
    "C"/"°C" -- asi reconoce cualquier chip de temperatura, y de paso evita
    falsos positivos de lineas de ventilador (RPM) o voltaje (V) que algunos
    chips de sensores de la board exponen en la misma salida de 'sensors'.

    Si el mismo nombre de sensor aparece en mas de un chip (ej. "Tctl" en
    cada socket de un servidor de 2 CPUs), el segundo en adelante se
    desambigua con el identificador del chip -- sin esto se pisarian entre
    si y se perderia la lectura de un socket completo. Los sensores de un
    solo chip (el caso de todos los despliegues actuales) no cambian de
    nombre, para no romper el historial ya guardado en Postgres.
    """
    temperaturas = {}
    chip_actual = ""
    for linea in salida_sensors.splitlines():
        linea_stripped = linea.strip()
        if not linea_stripped:
            chip_actual = ""
            continue
        if ":" not in linea_stripped:
            chip_actual = linea_stripped
            continue

        partes = linea.split(":")
        if len(partes) != 2:
            continue
        valores = partes[1].strip().split()
        if not valores:
            continue
        valor_crudo = valores[0]
        if not valor_crudo.endswith(("°C", "C")):
            continue

        nombre = partes[0].strip()
        valor_str = valor_crudo.replace("+", "").replace("°C", "").replace("C", "")
        try:
            valor = round(float(valor_str), 1)
        except ValueError:
            continue

        if nombre in temperaturas:
            nombre = f"{chip_actual}_{nombre}" if chip_actual else f"{nombre}_2"
        temperaturas[nombre] = valor
    return temperaturas

# ─── Parsear temperaturas CPU via thermal zones ───────────────────────────────
def parsear_cpu_thermal_zones():
    temperaturas = {}
    thermal_path = Path("/sys/class/thermal")
    zonas = sorted(thermal_path.glob("thermal_zone*"))
    for zona in zonas:
        try:
            tipo = (zona / "type").read_text().strip()
            temp_raw = int((zona / "temp").read_text().strip())
            temp = round(temp_raw / 1000, 1)  # Convertir de miligrados a grados
            nombre = f"{tipo}_{zona.name.replace('thermal_zone', '')}"
            temperaturas[nombre] = temp
        except Exception as e:
            logging.warning(f"Error leyendo {zona}: {e}")
    return temperaturas

# ─── Parsear temperatura GPU ──────────────────────────────────────────────────
def parsear_gpu(salida_nvidia):
    gpus = {}
    for i, linea in enumerate(salida_nvidia.splitlines()):
        try:
            gpus[f"GPU_{i}"] = round(float(linea.strip()), 1)
        except ValueError:
            pass
    return gpus

# ─── Leer uso de disco por punto de montaje ──────────────────────────────────
# Lista blanca de sistemas de archivos reales en vez de tratar de excluir cada
# pseudo-filesystem que existe (tmpfs, overlay, bpf, nsfs de Docker, etc. --
# la lista de esos nunca se termina de completar).
FILESYSTEMS_REALES = {"ext2", "ext3", "ext4", "xfs", "btrfs", "ntfs", "vfat", "exfat", "zfs", "reiserfs", "jfs", "f2fs"}


def parsear_volumen(dispositivo):
    """
    Agrupa por volumen: para un device-mapper de LVM, el grupo de volumenes
    (VG); para cualquier otro dispositivo, tal cual (ej. "/dev/sda2").
    LVM escapa un "-" literal del nombre como "--" -- el primer "-" sin
    escapar separa VG de LV (ver "man 7 lvm", seccion de nombres de dispositivo).
    """
    if dispositivo.startswith("/dev/mapper/"):
        nombre_mapper = dispositivo[len("/dev/mapper/"):]
        partes = re.split(r"(?<!-)-(?!-)", nombre_mapper)
        return partes[0].replace("--", "-")
    return dispositivo


def leer_uso_disco():
    """
    Lee /proc/mounts y regresa el uso de cada punto de montaje real.
    """
    usos = []
    try:
        with open("/proc/mounts") as f:
            lineas = f.readlines()
    except Exception as e:
        logging.warning(f"No se pudo leer /proc/mounts: {e}")
        return usos

    for linea in lineas:
        campos = linea.split()
        if len(campos) < 3:
            continue
        dispositivo, punto_montaje, tipo_fs = campos[0], campos[1], campos[2]
        if tipo_fs not in FILESYSTEMS_REALES:
            continue
        try:
            total, usado, _libre = shutil.disk_usage(punto_montaje)
        except OSError as e:
            logging.warning(f"No se pudo leer uso de {punto_montaje}: {e}")
            continue
        usos.append({
            "volumen": parsear_volumen(dispositivo),
            "punto_montaje": punto_montaje,
            "usado_gb": round(usado / 1024 ** 3, 1),
            "total_gb": round(total / 1024 ** 3, 1),
        })
    return usos


# ─── Guardar un lote de uso de disco ──────────────────────────────────────────
def guardar_lote_disco(directorio_salida, momento, datos_disco):
    """
    Un archivo por lote, igual que guardar_lote() -- "disco_<momento>.csv" en
    vez de "lecturas_<momento>.csv", asi la ingesta distingue el tipo de dato
    por el nombre del archivo.
    """
    if not datos_disco:
        return

    os.makedirs(directorio_salida, exist_ok=True)

    nombre_archivo = f"disco_{momento.strftime('%Y%m%d_%H%M%S')}.csv"
    ruta_archivo = os.path.join(directorio_salida, nombre_archivo)
    medido_en = momento.isoformat()

    with open(ruta_archivo, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["medido_en", "volumen", "punto_montaje", "usado_gb", "total_gb"])
        writer.writeheader()
        for dato in datos_disco:
            writer.writerow({"medido_en": medido_en, **dato})

    logging.info(f"Lote de disco guardado: {ruta_archivo} ({len(datos_disco)} montajes)")


# ─── Guardar un lote de lecturas (formato largo) ──────────────────────────────
def guardar_lote(directorio_salida, momento, datos_cpu, datos_gpu):
    """
    Escribe un archivo por lectura, en formato largo (medido_en, componente,
    sensor, temperatura_c), con las mismas columnas que la tabla 'lecturas'
    de Postgres. Un archivo por intervalo permite al modulo de ingesta
    borrarlo completo una vez cargado, sin riesgo de truncar un archivo que
    el colector siga escribiendo.
    """
    os.makedirs(directorio_salida, exist_ok=True)

    nombre_archivo = f"lecturas_{momento.strftime('%Y%m%d_%H%M%S')}.csv"
    ruta_archivo = os.path.join(directorio_salida, nombre_archivo)
    medido_en = momento.isoformat()

    filas = [
        {"medido_en": medido_en, "componente": "cpu", "sensor": sensor.replace(" ", "_"), "temperatura_c": valor}
        for sensor, valor in datos_cpu.items()
    ] + [
        {"medido_en": medido_en, "componente": "gpu", "sensor": sensor.replace(" ", "_"), "temperatura_c": valor}
        for sensor, valor in datos_gpu.items()
    ]

    with open(ruta_archivo, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["medido_en", "componente", "sensor", "temperatura_c"])
        writer.writeheader()
        writer.writerows(filas)

    logging.info(f"Lote guardado: {ruta_archivo} ({len(filas)} lecturas)")

# ─── Ciclo principal ──────────────────────────────────────────────────────────
def main():
    logging.info("=== Iniciando monitor de temperaturas ===")

    config            = cargar_configuracion()
    intervalo_min     = int(config["monitoreo"]["intervalo_minutos"])
    directorio_salida = config["almacenamiento"]["directorio_salida"]
    intervalo_seg     = intervalo_min * 60

    # Detectar metodos disponibles una sola vez al inicio
    metodo_cpu = detectar_metodo_cpu()
    tiene_gpu  = detectar_gpu()

    if not metodo_cpu and not tiene_gpu:
        logging.error("No se encontro ningun metodo de lectura de temperatura. Abortando.")
        return

    while True:
        momento = datetime.now(timezone.utc)
        logging.info(f"Iniciando lectura [{momento.isoformat()}]")

        try:
            datos_cpu = {}
            datos_gpu = {}

            # Leer CPU segun metodo detectado
            if metodo_cpu == "sensors":
                salida_sensors = ejecutar_comando("sensors")
                datos_cpu = parsear_cpu_sensors(salida_sensors)
            elif metodo_cpu == "thermal_zones":
                datos_cpu = parsear_cpu_thermal_zones()

            # Leer GPU si esta disponible
            if tiene_gpu:
                salida_nvidia = ejecutar_comando(
                    "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits"
                )
                datos_gpu = parsear_gpu(salida_nvidia)

            if not datos_cpu and not datos_gpu:
                logging.warning("No se obtuvieron temperaturas en esta lectura.")
            else:
                guardar_lote(directorio_salida, momento, datos_cpu, datos_gpu)

            datos_disco = leer_uso_disco()
            if not datos_disco:
                logging.warning("No se obtuvo uso de disco en esta lectura.")
            else:
                guardar_lote_disco(directorio_salida, momento, datos_disco)

        except Exception as e:
            logging.error(f"Error durante la lectura: {e}")

        logging.info(f"Proxima lectura en {intervalo_min} minutos.")
        time.sleep(intervalo_seg)


if __name__ == "__main__":
    main()
