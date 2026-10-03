import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_DIR / ".env")


def conectar_db():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def elegir_servidor(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.nombre, s.activo, COUNT(l.id)
            FROM servidores s
            LEFT JOIN lecturas l ON l.servidor_id = s.id
            GROUP BY s.id, s.nombre, s.activo
            ORDER BY s.nombre
            """
        )
        filas = cur.fetchall()

    if not filas:
        print("No hay servidores en la base de datos.")
        sys.exit(1)

    print("Servidores en la base de datos:")
    for i, (_, nombre, activo, n_lecturas) in enumerate(filas, 1):
        estado = "online" if activo else "offline"
        print(f"  {i}. {nombre} ({estado}, {n_lecturas} lecturas)")

    eleccion = input("Elige el numero del servidor a eliminar: ").strip()
    try:
        return filas[int(eleccion) - 1][1]
    except (ValueError, IndexError):
        print("Opcion invalida.")
        sys.exit(1)


def limpiar_grupos_vacios(conn, grupo_id):
    """Sube por el arbol borrando grupos que se quedaron sin servidores ni subgrupos."""
    borrados = []
    with conn.cursor() as cur:
        while grupo_id is not None:
            cur.execute("SELECT COUNT(*) FROM servidores WHERE grupo_id = %s", (grupo_id,))
            tiene_servidores = cur.fetchone()[0] > 0
            cur.execute("SELECT COUNT(*) FROM grupos WHERE grupo_padre_id = %s", (grupo_id,))
            tiene_subgrupos = cur.fetchone()[0] > 0

            if tiene_servidores or tiene_subgrupos:
                break

            cur.execute("SELECT nombre, grupo_padre_id FROM grupos WHERE id = %s", (grupo_id,))
            nombre, grupo_padre_id = cur.fetchone()
            cur.execute("DELETE FROM grupos WHERE id = %s", (grupo_id,))
            borrados.append(nombre)
            grupo_id = grupo_padre_id
    return borrados


def main():
    conn = conectar_db()

    nombre = sys.argv[1] if len(sys.argv) > 1 else elegir_servidor(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT id, grupo_id FROM servidores WHERE nombre = %s", (nombre,))
        fila = cur.fetchone()
        if fila is None:
            print(f"No existe ningun servidor llamado '{nombre}'.")
            sys.exit(1)
        servidor_id, grupo_id = fila

        cur.execute("SELECT COUNT(*) FROM lecturas WHERE servidor_id = %s", (servidor_id,))
        n_lecturas = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM archivos_ingeridos WHERE servidor_id = %s", (servidor_id,))
        n_archivos = cur.fetchone()[0]

    print(f"\nEsto borrara PERMANENTEMENTE a '{nombre}' de la base de datos:")
    print(f"  - {n_lecturas} lecturas")
    print(f"  - {n_archivos} registros de archivos ya ingeridos")
    print("Tambien quitalo de 'inventario_servidores.yaml' si es un retiro definitivo")
    print("(este script solo limpia Postgres, no toca el inventario).")
    confirmacion = input("Escribe 'si' para continuar: ").strip().lower()
    if confirmacion != "si":
        print("Cancelado.")
        return

    with conn.cursor() as cur:
        cur.execute("DELETE FROM archivos_ingeridos WHERE servidor_id = %s", (servidor_id,))
        cur.execute("DELETE FROM lecturas WHERE servidor_id = %s", (servidor_id,))
        cur.execute("DELETE FROM servidores WHERE id = %s", (servidor_id,))
    conn.commit()
    print(f"'{nombre}' eliminado.")

    grupos_borrados = limpiar_grupos_vacios(conn, grupo_id)
    conn.commit()
    if grupos_borrados:
        print(f"Grupos vacios tambien eliminados: {', '.join(grupos_borrados)}")

    conn.close()


if __name__ == "__main__":
    main()
