import csv
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

load_dotenv(PROJECT_DIR / ".env")


def conectar_db():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def obtener_servidor_id(conn, nombre):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO servidores (nombre, sistema_operativo, activo)
            VALUES (%s, 'ubuntu', true)
            ON CONFLICT (nombre) DO NOTHING
            """,
            (nombre,),
        )
        cur.execute("SELECT id FROM servidores WHERE nombre = %s", (nombre,))
        servidor_id = cur.fetchone()[0]
    conn.commit()
    return servidor_id


def parsear_csv_viejo(ruta_csv):
    """
    Formato viejo (CSV ancho, proyecto Monit_Servers): timestamp,cpu_<sensor>,...,gpu_<sensor>,...
    Devuelve filas (medido_en, componente, sensor, temperatura_c) en formato largo.
    """
    filas = []
    with open(ruta_csv, encoding="utf-8") as f:
        lector = csv.DictReader(f)
        columnas_sensor = [c for c in lector.fieldnames if c != "timestamp"]

        for fila in lector:
            medido_en = fila["timestamp"]
            for columna in columnas_sensor:
                valor = fila.get(columna)
                if not valor:
                    continue
                componente, _, sensor = columna.partition("_")
                if componente not in ("cpu", "gpu"):
                    continue
                try:
                    temperatura = float(valor)
                except ValueError:
                    continue
                filas.append((medido_en, componente, sensor, temperatura))
    return filas


def main():
    if len(sys.argv) < 2:
        print("Uso: python migrar_historico_csv.py <carpeta_con_csv_viejos>")
        print(r'Ej:  python migrar_historico_csv.py "C:\Users\Meki\Documents\Quantum\Monit_Servers\CSV"')
        sys.exit(1)

    carpeta = Path(sys.argv[1])
    archivos = sorted(carpeta.glob("*.csv"))
    if not archivos:
        print(f"No se encontraron .csv en {carpeta}")
        sys.exit(1)

    conn = conectar_db()
    total_general = 0

    for archivo in archivos:
        nombre_servidor = archivo.stem
        filas = parsear_csv_viejo(archivo)
        if not filas:
            print(f"[{nombre_servidor}] Sin filas validas, se omite.")
            continue

        servidor_id = obtener_servidor_id(conn, nombre_servidor)

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
        conn.commit()
        print(f"[{nombre_servidor}] {len(filas)} lecturas procesadas desde {archivo.name}")
        total_general += len(filas)

    conn.close()
    print(f"\nMigracion completada: {total_general} lecturas procesadas en total.")


if __name__ == "__main__":
    main()
