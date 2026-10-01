import os
import shutil
import subprocess
import sys
from glob import glob
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
ORIGEN = PROJECT_DIR / "bkp" / "Data_Base"

load_dotenv(PROJECT_DIR / ".env")


def encontrar_binario(nombre):
    encontrado = shutil.which(nombre)
    if encontrado:
        return encontrado
    candidatos = sorted(glob(rf"C:\Program Files\PostgreSQL\*\bin\{nombre}.exe"), reverse=True)
    if candidatos:
        return candidatos[0]
    raise FileNotFoundError(f"No se encontro {nombre}. Instala el cliente de PostgreSQL o agregalo al PATH.")


def elegir_archivo():
    archivos = sorted(ORIGEN.glob("*.sql"), reverse=True)
    if not archivos:
        print(f"No hay respaldos en {ORIGEN}")
        sys.exit(1)

    print("Respaldos disponibles:")
    for i, archivo in enumerate(archivos, 1):
        print(f"  {i}. {archivo.name}")

    eleccion = input("Elige el numero del respaldo a restaurar: ").strip()
    try:
        return archivos[int(eleccion) - 1]
    except (ValueError, IndexError):
        print("Opcion invalida.")
        sys.exit(1)


def asegurar_base_existe():
    """Si la base no existe (ej. maquina recien formateada), la crea antes de restaurar."""
    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname="postgres",
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (os.environ["DB_NAME"],))
        if cur.fetchone() is None:
            print(f"La base '{os.environ['DB_NAME']}' no existe, se crea antes de restaurar...")
            cur.execute(f'CREATE DATABASE "{os.environ["DB_NAME"]}"')
    conn.close()


def main():
    ruta_archivo = Path(sys.argv[1]) if len(sys.argv) > 1 else elegir_archivo()
    if not ruta_archivo.exists():
        print(f"No existe el archivo: {ruta_archivo}")
        sys.exit(1)

    print(f"\nEsto SOBREESCRIBIRA por completo la base '{os.environ['DB_NAME']}' con el contenido de:")
    print(f"  {ruta_archivo}")
    confirmacion = input("Escribe 'si' para continuar: ").strip().lower()
    if confirmacion != "si":
        print("Cancelado.")
        return

    asegurar_base_existe()

    psql = encontrar_binario("psql")
    comando = [
        psql,
        "-h", os.environ["DB_HOST"],
        "-p", os.environ.get("DB_PORT", "5432"),
        "-U", os.environ["DB_USER"],
        "-d", os.environ["DB_NAME"],
        "-f", str(ruta_archivo),
    ]
    entorno = os.environ.copy()
    entorno["PGPASSWORD"] = os.environ["DB_PASSWORD"]

    resultado = subprocess.run(comando, env=entorno, capture_output=True, text=True)
    print(resultado.stdout)
    if resultado.returncode != 0:
        print("Error al restaurar:")
        print(resultado.stderr)
        sys.exit(1)

    print("Restauracion completada.")


if __name__ == "__main__":
    main()
