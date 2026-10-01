import os
from pathlib import Path

import yaml
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

load_dotenv(PROJECT_DIR / ".env")

with open(BASE_DIR / "umbrales.yaml", encoding="utf-8") as f:
    UMBRALES = yaml.safe_load(f)

app = FastAPI(title="Monit Servers V2 - API")


def conectar_db():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def calcular_estado(componente, temperatura_c):
    rangos = UMBRALES.get(componente)
    if rangos is None:
        return None
    if temperatura_c <= rangos["verde_max"]:
        return "verde"
    if temperatura_c <= rangos["ambar_max"]:
        return "ambar"
    return "rojo"


def obtener_servidor_id(cur, nombre):
    cur.execute("SELECT id FROM servidores WHERE nombre = %s", (nombre,))
    fila = cur.fetchone()
    if fila is None:
        raise HTTPException(status_code=404, detail=f"Servidor '{nombre}' no encontrado")
    return fila["id"]


@app.get("/api/health")
def salud():
    return {"status": "ok"}


@app.get("/api/servidores")
def listar_servidores():
    with conectar_db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, nombre, sistema_operativo, activo FROM servidores ORDER BY nombre")
        return cur.fetchall()


@app.get("/api/servidores/{nombre}/actual")
def temperatura_actual(nombre: str):
    with conectar_db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        servidor_id = obtener_servidor_id(cur, nombre)
        cur.execute(
            """
            SELECT DISTINCT ON (componente, sensor)
                componente, sensor, temperatura_c, medido_en
            FROM lecturas
            WHERE servidor_id = %s
            ORDER BY componente, sensor, medido_en DESC
            """,
            (servidor_id,),
        )
        filas = cur.fetchall()

    for fila in filas:
        fila["estado"] = calcular_estado(fila["componente"], float(fila["temperatura_c"]))
    return filas


@app.get("/api/servidores/{nombre}/historico")
def historico(nombre: str, agrupacion: str = Query("hora", pattern="^(hora|dia|mes)$")):
    unidad_sql = {"hora": "hour", "dia": "day", "mes": "month"}[agrupacion]

    with conectar_db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        servidor_id = obtener_servidor_id(cur, nombre)
        cur.execute(
            """
            SELECT
                componente,
                sensor,
                date_trunc(%s, medido_en) AS periodo,
                AVG(temperatura_c)::numeric(5,1) AS temperatura_promedio
            FROM lecturas
            WHERE servidor_id = %s
            GROUP BY componente, sensor, periodo
            ORDER BY periodo
            """,
            (unidad_sql, servidor_id),
        )
        return cur.fetchall()


# Debe montarse al final: las rutas /api/* ya registradas arriba se
# resuelven antes de caer a este catch-all de archivos estaticos en "/".
app.mount("/", StaticFiles(directory=str(PROJECT_DIR / "dashboard"), html=True), name="dashboard")
