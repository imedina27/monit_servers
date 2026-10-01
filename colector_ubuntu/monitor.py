import csv
import os
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
        # Verificar que sensors devuelve datos utiles
        salida = ejecutar_comando("sensors")
        if "Core" in salida or "Package" in salida:
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
    temperaturas = {}
    for linea in salida_sensors.splitlines():
        if any(clave in linea for clave in ["Core", "Package"]):
            partes = linea.split(":")
            if len(partes) == 2:
                nombre = partes[0].strip()
                valor_str = partes[1].strip().split()[0]
                valor_str = valor_str.replace("+", "").replace("°C", "").replace("C", "")
                try:
                    temperaturas[nombre] = round(float(valor_str), 1)
                except ValueError:
                    pass
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

        except Exception as e:
            logging.error(f"Error durante la lectura: {e}")

        logging.info(f"Proxima lectura en {intervalo_min} minutos.")
        time.sleep(intervalo_seg)


if __name__ == "__main__":
    main()
