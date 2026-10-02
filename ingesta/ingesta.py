import os
import csv
import logging
import configparser
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml
import paramiko
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
LOG_FILE = os.path.join(BASE_DIR, "ingesta.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

load_dotenv(os.path.join(PROJECT_DIR, ".env"))


# ─── Configuracion e inventario ───────────────────────────────────────────────
def cargar_configuracion():
    config = configparser.ConfigParser()
    config.read(os.path.join(BASE_DIR, "config.ini"), encoding="utf-8")
    return config


def cargar_inventario():
    ruta = os.path.join(PROJECT_DIR, "inventario_servidores.yaml")
    if not os.path.exists(ruta):
        raise FileNotFoundError(
            f"No se encontro {ruta}. Copia inventario_servidores.yaml.example y completa los datos reales."
        )
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f)
    return {s["nombre"]: s for s in datos["servidores"]}


# ─── Base de datos ─────────────────────────────────────────────────────────────
def conectar_db():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def obtener_grupo_id(conn, ruta_grupo):
    """
    Crea (si hace falta) la cadena de grupos para una ruta tipo carpeta
    ("Cliente/Ciudad") y devuelve el id del grupo mas profundo (la hoja de
    la que cuelga el servidor). None si no se especifico 'grupo'.

    No usa ON CONFLICT: el UNIQUE (nombre, grupo_padre_id) no detecta
    duplicados cuando grupo_padre_id es NULL (nivel raiz), porque NULL no
    es igual a NULL para una restriccion unica. Se busca primero y solo se
    inserta si de verdad no existe.
    """
    if not ruta_grupo:
        return None

    grupo_padre_id = None
    with conn.cursor() as cur:
        for nombre_grupo in (p.strip() for p in ruta_grupo.split("/") if p.strip()):
            if grupo_padre_id is None:
                cur.execute("SELECT id FROM grupos WHERE nombre = %s AND grupo_padre_id IS NULL", (nombre_grupo,))
            else:
                cur.execute("SELECT id FROM grupos WHERE nombre = %s AND grupo_padre_id = %s", (nombre_grupo, grupo_padre_id))
            fila = cur.fetchone()
            if fila:
                grupo_padre_id = fila[0]
            else:
                cur.execute(
                    "INSERT INTO grupos (nombre, grupo_padre_id) VALUES (%s, %s) RETURNING id",
                    (nombre_grupo, grupo_padre_id),
                )
                grupo_padre_id = cur.fetchone()[0]
    conn.commit()
    return grupo_padre_id


def obtener_servidor_id(conn, nombre, sistema_operativo, activo, grupo_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO servidores (nombre, sistema_operativo, activo, grupo_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (nombre) DO UPDATE
                SET sistema_operativo = EXCLUDED.sistema_operativo,
                    activo = EXCLUDED.activo,
                    grupo_id = EXCLUDED.grupo_id
            RETURNING id
            """,
            (nombre, sistema_operativo, activo, grupo_id),
        )
        servidor_id = cur.fetchone()[0]
    conn.commit()
    return servidor_id


def ya_ingerido(conn, servidor_id, nombre_archivo):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM archivos_ingeridos WHERE servidor_id = %s AND nombre_archivo = %s",
            (servidor_id, nombre_archivo),
        )
        return cur.fetchone() is not None


def insertar_lote(conn, servidor_id, nombre_archivo, origen, filas):
    """
    Inserta las lecturas y registra el archivo como ingerido en una sola
    transaccion. Solo si esto confirma (commit) se debe borrar el archivo
    de origen (online o offline).
    """
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO lecturas (servidor_id, medido_en, componente, sensor, temperatura_c)
            VALUES %s
            ON CONFLICT (servidor_id, medido_en, sensor) DO NOTHING
            """,
            [(servidor_id, *fila) for fila in filas],
        )
        cur.execute(
            """
            INSERT INTO archivos_ingeridos (servidor_id, nombre_archivo, origen, filas_cargadas)
            VALUES (%s, %s, %s, %s)
            """,
            (servidor_id, nombre_archivo, origen, len(filas)),
        )
    conn.commit()


# ─── Parseo del formato largo (igual al que escribe el colector) ──────────────
def parsear_lote(contenido):
    lector = csv.DictReader(contenido.splitlines())
    return [
        (fila["medido_en"], fila["componente"], fila["sensor"], float(fila["temperatura_c"]))
        for fila in lector
    ]


# ─── Ingesta online (SSH/SFTP) ────────────────────────────────────────────────
def procesar_online(nombre, servidor):
    """
    Abre su propia conexion a la BD y al servidor (se ejecuta en su propio
    hilo). Descarga cada archivo pendiente directo a memoria, lo carga a la
    BD, y solo si eso tuvo exito lo borra del servidor.
    """
    conn = conectar_db()
    procesados, omitidos = 0, 0
    try:
        grupo_id = obtener_grupo_id(conn, servidor.get("grupo"))
        servidor_id = obtener_servidor_id(conn, nombre, servidor["sistema_operativo"], servidor.get("activo", True), grupo_id)

        cliente = paramiko.SSHClient()
        cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cliente.connect(
            hostname=servidor["ip"],
            port=servidor.get("puerto", 22),
            username=servidor["usuario"],
            password=servidor["password"],
            timeout=15,
        )
        sftp = cliente.open_sftp()
        try:
            archivos = sorted(f for f in sftp.listdir(servidor["directorio_remoto"]) if f.endswith(".csv"))
        except FileNotFoundError:
            logging.warning(f"[{nombre}] Directorio remoto no existe: {servidor['directorio_remoto']}")
            archivos = []

        for nombre_archivo in archivos:
            if ya_ingerido(conn, servidor_id, nombre_archivo):
                omitidos += 1
                continue

            ruta_remota = f"{servidor['directorio_remoto']}/{nombre_archivo}"
            with sftp.open(ruta_remota, "r") as f:
                contenido = f.read().decode("utf-8")

            filas = parsear_lote(contenido)
            insertar_lote(conn, servidor_id, nombre_archivo, "online", filas)

            try:
                sftp.remove(ruta_remota)
            except Exception as e:
                logging.warning(f"[{nombre}] Cargado pero no se pudo borrar {nombre_archivo} del servidor: {e}")

            logging.info(f"[{nombre}] Cargado: {nombre_archivo} ({len(filas)} lecturas)")
            procesados += 1

        sftp.close()
        cliente.close()
    finally:
        conn.close()

    return procesados, omitidos


# ─── Ingesta offline (archivos locales) ───────────────────────────────────────
def procesar_offline(directorio_offline, inventario):
    conn = conectar_db()
    total_procesados = 0
    try:
        if not os.path.isdir(directorio_offline):
            return 0

        for nombre_carpeta in sorted(os.listdir(directorio_offline)):
            ruta_servidor = os.path.join(directorio_offline, nombre_carpeta)
            if not os.path.isdir(ruta_servidor):
                continue

            servidor = inventario.get(nombre_carpeta)
            if servidor is None:
                logging.warning(
                    f"Carpeta offline '{nombre_carpeta}' no coincide con ningun servidor "
                    f"del inventario, se omite."
                )
                continue

            grupo_id = obtener_grupo_id(conn, servidor.get("grupo"))
            servidor_id = obtener_servidor_id(conn, nombre_carpeta, servidor["sistema_operativo"], servidor.get("activo", True), grupo_id)

            for nombre_archivo in sorted(os.listdir(ruta_servidor)):
                if not nombre_archivo.endswith(".csv"):
                    continue
                if ya_ingerido(conn, servidor_id, nombre_archivo):
                    continue

                ruta_archivo = os.path.join(ruta_servidor, nombre_archivo)
                with open(ruta_archivo, encoding="utf-8") as f:
                    contenido = f.read()

                filas = parsear_lote(contenido)
                insertar_lote(conn, servidor_id, nombre_archivo, "offline", filas)

                try:
                    os.remove(ruta_archivo)
                except Exception as e:
                    logging.warning(f"[{nombre_carpeta}] Cargado pero no se pudo borrar {nombre_archivo}: {e}")

                logging.info(f"[{nombre_carpeta}] Cargado (offline): {nombre_archivo} ({len(filas)} lecturas)")
                total_procesados += 1
    finally:
        conn.close()

    return total_procesados


def sincronizar_todo(inventario):
    """
    Da de alta/actualiza TODOS los servidores del inventario y sus grupos
    (activos o no), para que el arbol del dashboard los vea aunque todavia
    no se les este descargando informacion (ej. servidores de alta futura).
    """
    conn = conectar_db()
    try:
        for nombre, servidor in inventario.items():
            grupo_id = obtener_grupo_id(conn, servidor.get("grupo"))
            obtener_servidor_id(conn, nombre, servidor["sistema_operativo"], servidor.get("activo", True), grupo_id)
    finally:
        conn.close()


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    logging.info("=== Iniciando ingesta ===")

    config = cargar_configuracion()
    max_workers = int(config["ingesta"]["max_workers"])
    directorio_offline = os.path.join(PROJECT_DIR, config["ingesta"]["directorio_offline"])

    inventario = cargar_inventario()
    sincronizar_todo(inventario)
    activos = {nombre: s for nombre, s in inventario.items() if s.get("activo", True)}

    total_procesados, total_omitidos = 0, 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futuros = {pool.submit(procesar_online, nombre, s): nombre for nombre, s in activos.items()}
        for futuro in as_completed(futuros):
            nombre = futuros[futuro]
            try:
                procesados, omitidos = futuro.result()
                total_procesados += procesados
                total_omitidos += omitidos
            except Exception as e:
                logging.error(f"[{nombre}] Error en ingesta online: {e}")

    offline_procesados = procesar_offline(directorio_offline, inventario)

    logging.info(
        f"Ingesta completada: {total_procesados} archivos online cargados, "
        f"{total_omitidos} ya estaban cargados, {offline_procesados} archivos offline cargados."
    )


if __name__ == "__main__":
    main()
