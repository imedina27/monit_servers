import os
import shutil
import subprocess
import sys
from datetime import datetime
from glob import glob
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DESTINO = PROJECT_DIR / "bkp" / "Data_Base"

load_dotenv(PROJECT_DIR / ".env")


def encontrar_binario(nombre):
    encontrado = shutil.which(nombre)
    if encontrado:
        return encontrado
    candidatos = sorted(glob(rf"C:\Program Files\PostgreSQL\*\bin\{nombre}.exe"), reverse=True)
    if candidatos:
        return candidatos[0]
    raise FileNotFoundError(f"No se encontro {nombre}. Instala el cliente de PostgreSQL o agregalo al PATH.")


def main():
    pg_dump = encontrar_binario("pg_dump")
    DESTINO.mkdir(parents=True, exist_ok=True)

    nombre_archivo = f"{os.environ['DB_NAME']}_{datetime.now().strftime('%d%m%y')}.sql"
    ruta_salida = DESTINO / nombre_archivo

    comando = [
        pg_dump,
        "--clean", "--if-exists",
        "-h", os.environ["DB_HOST"],
        "-p", os.environ.get("DB_PORT", "5432"),
        "-U", os.environ["DB_USER"],
        "-d", os.environ["DB_NAME"],
        "-f", str(ruta_salida),
    ]

    entorno = os.environ.copy()
    entorno["PGPASSWORD"] = os.environ["DB_PASSWORD"]

    print(f"Respaldando '{os.environ['DB_NAME']}' en {ruta_salida} ...")
    resultado = subprocess.run(comando, env=entorno, capture_output=True, text=True)

    if resultado.returncode != 0:
        print("Error al respaldar:")
        print(resultado.stderr)
        sys.exit(1)

    print(f"Respaldo completado: {ruta_salida}")


if __name__ == "__main__":
    main()
