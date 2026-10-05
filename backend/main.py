import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

load_dotenv(PROJECT_DIR / ".env")

# Para poder llamar a ingesta.main() directo (boton "Actualizar" del dashboard),
# sin tener que lanzar un proceso aparte.
sys.path.insert(0, str(PROJECT_DIR / "ingesta"))

# Fallback cuando un servidor no tiene fila propia en la tabla 'umbrales' --
# no es dato de ningun servidor en particular, por eso vive aqui y no en la BD.
UMBRALES_DEFAULT = {
    "cpu": {"verde_max": 70, "ambar_max": 85},
    "gpu": {"verde_max": 75, "ambar_max": 85},
}

app = FastAPI(title="Monit Servers V2 - API")


def conectar_db():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def calcular_estado(rangos, temperatura_c):
    if rangos is None:
        return None
    if temperatura_c <= rangos["verde_max"]:
        return "verde"
    if temperatura_c <= rangos["ambar_max"]:
        return "ambar"
    return "rojo"


def obtener_umbrales_servidor(cur, servidor_id):
    cur.execute(
        "SELECT componente, verde_max, ambar_max FROM umbrales WHERE servidor_id = %s",
        (servidor_id,),
    )
    return {
        fila["componente"]: {"verde_max": float(fila["verde_max"]), "ambar_max": float(fila["ambar_max"])}
        for fila in cur.fetchall()
    }


def obtener_servidor_id(cur, nombre):
    cur.execute("SELECT id FROM servidores WHERE nombre = %s", (nombre,))
    fila = cur.fetchone()
    if fila is None:
        raise HTTPException(status_code=404, detail=f"Servidor '{nombre}' no encontrado")
    return fila["id"]


@app.get("/api/health")
def salud():
    return {"status": "ok"}


@app.post("/api/ingesta/ejecutar")
def ejecutar_ingesta():
    """
    Dispara la ingesta bajo demanda (boton "Actualizar" del dashboard).
    Corre en el mismo proceso del backend -- FastAPI ejecuta los endpoints
    sincronos en un hilo aparte, asi que no bloquea otras peticiones.
    """
    import ingesta as modulo_ingesta

    try:
        return modulo_ingesta.main()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al ejecutar la ingesta: {e}")


@app.get("/api/servidores")
def listar_servidores():
    with conectar_db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, nombre, sistema_operativo, activo FROM servidores ORDER BY orden")
        return cur.fetchall()


@app.get("/api/grupos")
def listar_arbol():
    """
    Arbol de grupos (cliente -> ubicacion -> ... , profundidad libre) con los
    servidores como hojas, para el sidebar del dashboard. El grupo_padre_id
    de cada grupo arma la jerarquia; los servidores sin grupo_id se agrupan
    aparte para no perderlos de vista.
    """
    with conectar_db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, nombre, grupo_padre_id FROM grupos ORDER BY orden")
        grupos = cur.fetchall()
        cur.execute("SELECT nombre, grupo_id, activo FROM servidores WHERE grupo_id IS NOT NULL ORDER BY orden")
        servidores = cur.fetchall()
        cur.execute("SELECT nombre, activo FROM servidores WHERE grupo_id IS NULL ORDER BY orden")
        sin_grupo = cur.fetchall()

    nodos = {g["id"]: {"tipo": "grupo", "nombre": g["nombre"], "hijos": []} for g in grupos}
    raiz = []
    for g in grupos:
        nodo = nodos[g["id"]]
        if g["grupo_padre_id"] is None:
            raiz.append(nodo)
        else:
            nodos[g["grupo_padre_id"]]["hijos"].append(nodo)

    for s in servidores:
        nodos[s["grupo_id"]]["hijos"].append({"tipo": "servidor", "nombre": s["nombre"], "activo": s["activo"]})

    if sin_grupo:
        raiz.append({
            "tipo": "grupo",
            "nombre": "Sin grupo",
            "hijos": [{"tipo": "servidor", "nombre": s["nombre"], "activo": s["activo"]} for s in sin_grupo],
        })

    return raiz


@app.get("/api/servidores/{nombre}/actual")
def temperatura_actual(nombre: str):
    with conectar_db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        servidor_id = obtener_servidor_id(cur, nombre)
        umbrales_servidor = obtener_umbrales_servidor(cur, servidor_id)
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
        rangos = umbrales_servidor.get(fila["componente"]) or UMBRALES_DEFAULT.get(fila["componente"])
        fila["estado"] = calcular_estado(rangos, float(fila["temperatura_c"]))
    return filas


@app.get("/api/servidores/{nombre}/hardware")
def hardware_servidor(nombre: str):
    with conectar_db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        servidor_id = obtener_servidor_id(cur, nombre)

        resultado = {}

        cur.execute(
            "SELECT marca, modelo, numero_serie, so_version, garantia FROM hardware_chassis WHERE servidor_id = %s",
            (servidor_id,),
        )
        fila = cur.fetchone()
        if fila:
            resultado["chasis"] = fila

        cur.execute("SELECT modelo, nucleos FROM hardware_cpu WHERE servidor_id = %s", (servidor_id,))
        fila = cur.fetchone()
        if fila:
            resultado["cpu_modelo"] = fila["modelo"]
            resultado["cpu_nucleos"] = fila["nucleos"]

        cur.execute("SELECT modelo, nucleos FROM hardware_gpu WHERE servidor_id = %s", (servidor_id,))
        fila = cur.fetchone()
        if fila:
            resultado["gpu_modelo"] = fila["modelo"]
            resultado["gpu_nucleos"] = fila["nucleos"]

        cur.execute("SELECT total_gb, velocidad_mhz FROM hardware_ram WHERE servidor_id = %s", (servidor_id,))
        fila = cur.fetchone()
        if fila:
            resultado["ram_total_gb"] = fila["total_gb"]
            resultado["ram_velocidad_mhz"] = fila["velocidad_mhz"]

        cur.execute(
            "SELECT slot, estado, capacidad_mb, velocidad_mhz FROM hardware_dimms WHERE servidor_id = %s ORDER BY id",
            (servidor_id,),
        )
        resultado["dimms"] = cur.fetchall()

        cur.execute(
            "SELECT marca, modelo, tipo, capacidad, transporte FROM discos WHERE servidor_id = %s ORDER BY id",
            (servidor_id,),
        )
        resultado["discos"] = cur.fetchall()

        cur.execute(
            "SELECT tipo, nivel, descripcion FROM raid WHERE servidor_id = %s ORDER BY id",
            (servidor_id,),
        )
        resultado["raid"] = cur.fetchall()

    return resultado


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
