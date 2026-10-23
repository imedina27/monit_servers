"""
Levanta el sandbox completo de "Tiempo Real" en un solo proceso Python, SIN
Docker ni WSL -- 3 servidores SSH falsos (servidor_falso.py) en distintos
puertos de 127.0.0.1:

  - 2203: "sandbox_directo"   (con GPU)
  - 2204: "sandbox_companero" (sin GPU, solo alcanzable "desde" el gateway)
  - 2202: "sandbox_gateway"   (con GPU + delega a sandbox_companero,
           corriendo relay/leer_companero.py de verdad en este mismo proceso)

Uso: python sandbox/levantar_sandbox.py
Dejar corriendo en una terminal aparte; Ctrl+C para apagar.
"""
import json
import shlex
import sys
import threading
from pathlib import Path

SANDBOX_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SANDBOX_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(SANDBOX_DIR))

import os  # noqa: E402

os.environ["COMPANEROS_PATH"] = str(SANDBOX_DIR / "companeros.local.yaml")

from relay import leer_companero  # noqa: E402
import servidor_falso  # noqa: E402

PUERTO_DIRECTO = 2203
PUERTO_COMPANERO = 2204
PUERTO_GATEWAY = 2202


def ejecutor_leer_companero(comando):
    """El backend real invoca 'python3 <ruta_repo>/relay/leer_companero.py
    <nombre>' por exec_command en el gateway -- aqui, en vez de lanzar un
    proceso python3 de verdad, se llama a la MISMA funcion de
    relay/leer_companero.py directo (ya esta en este proceso), que a su vez
    abre una conexion SSH real hacia 127.0.0.1:2204 (sandbox_companero)."""
    partes = shlex.split(comando)
    if len(partes) < 2 or not partes[-2].endswith("leer_companero.py"):
        return "", f"[sandbox] comando de gateway no reconocido: {comando}", 1

    nombre = partes[-1]
    try:
        resultado = leer_companero.leer_companero(nombre)
    except Exception as e:
        return "", f"Error leyendo companero '{nombre}': {e}", 1
    return json.dumps(resultado) + "\n", "", 0


def main():
    hilos = [
        threading.Thread(target=servidor_falso.servir, kwargs=dict(
            puerto=PUERTO_DIRECTO, con_gpu=True, etiqueta="sandbox_directo",
        ), daemon=True),
        threading.Thread(target=servidor_falso.servir, kwargs=dict(
            puerto=PUERTO_COMPANERO, con_gpu=False, etiqueta="sandbox_companero",
        ), daemon=True),
        threading.Thread(target=servidor_falso.servir, kwargs=dict(
            puerto=PUERTO_GATEWAY, con_gpu=True, ejecutor_extra=ejecutor_leer_companero,
            etiqueta="sandbox_gateway",
        ), daemon=True),
    ]
    for h in hilos:
        h.start()

    print()
    print("Sandbox listo. Para probar sin tocar Postgres/FastAPI:")
    print()
    print("  INVENTARIO_PATH=sandbox/inventario_servidores.sandbox.yaml python -c \"")
    print("  import sys; sys.path.insert(0, 'backend')")
    print("  import ssh_lectura_directa as t")
    print("  print(t.obtener_lectura('sandbox_directo'))")
    print("  print(t.obtener_lectura('sandbox_companero'))")
    print("  \"")
    print()
    print("Ctrl+C para apagar.")

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nApagando sandbox.")


if __name__ == "__main__":
    main()
