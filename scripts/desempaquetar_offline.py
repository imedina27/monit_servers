"""
Procesa los .zip que genera relay/empaquetar_offline.py en sitios 100%
offline (ej. AbInBev): los descomprime, sube cada subcarpeta (una por
servidor) a DEVELOP por SFTP, dispara la ingesta una sola vez al final, y
borra cada .zip en cuanto su contenido ya quedo subido.

Uso: python scripts/desempaquetar_offline.py

Procesa TODOS los .zip que encuentre en relay/zips/ (bandeja de entrada) --
no hace falta indicar un archivo en particular, solo deja ahi los que traigas
de cada visita al sitio.

Requiere las mismas variables DEVELOP_* en .env que cargar_offline_remoto.py
(mismo .env, ver .env.example).
"""
import sys
import tempfile
import urllib.error
import zipfile
from pathlib import Path

from cargar_offline_remoto import subir_bundle, disparar_ingesta

PROJECT_DIR = Path(__file__).resolve().parent.parent
ZIPS_DIR = PROJECT_DIR / "relay" / "zips"


def procesar_zip(ruta_zip):
    """Sube cada subcarpeta del zip a DEVELOP. True si todo salio bien (el
    zip ya se puede borrar), False si algo fallo (se deja para reintentar)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            with zipfile.ZipFile(ruta_zip) as zf:
                if zf.testzip() is not None:
                    print(f"  ERROR: '{ruta_zip.name}' esta corrupto, se omite.", file=sys.stderr)
                    return False
                zf.extractall(temp_dir)
        except zipfile.BadZipFile:
            print(f"  ERROR: '{ruta_zip.name}' no es un .zip valido, se omite.", file=sys.stderr)
            return False

        carpetas = sorted(p for p in Path(temp_dir).iterdir() if p.is_dir())
        if not carpetas:
            print(f"  '{ruta_zip.name}' no trae ninguna carpeta de servidor, se omite.")
            return False

        for carpeta in carpetas:
            nombre_servidor = carpeta.name
            print(f"  [{nombre_servidor}] subiendo...")
            n = subir_bundle(carpeta, nombre_servidor)
            print(f"  [{nombre_servidor}] {n} archivo(s) subido(s).")

    return True


def main():
    if not ZIPS_DIR.is_dir():
        print(f"No existe {ZIPS_DIR}, nada que procesar.")
        return

    zips = sorted(ZIPS_DIR.glob("*.zip"))
    if not zips:
        print(f"No hay .zip en {ZIPS_DIR}, nada que hacer.")
        return

    algo_subido = False
    for ruta_zip in zips:
        print(f"\nProcesando {ruta_zip.name}...")
        if procesar_zip(ruta_zip):
            ruta_zip.unlink()
            print(f"  Borrado: {ruta_zip.name}")
            algo_subido = True

    if not algo_subido:
        print("\nNingun zip se subio correctamente, no se dispara la ingesta.")
        return

    print("\nDisparando ingesta en DEVELOP...")
    try:
        resultado = disparar_ingesta()
    except urllib.error.URLError as e:
        print(f"Error al llamar la ingesta: {e}", file=sys.stderr)
        print("Los archivos ya quedaron subidos -- se cargaran solos en la siguiente ingesta (Ofelia, cada hora).")
        sys.exit(1)

    print(
        f"Ingesta completada: {resultado['online_cargados']} online cargados, "
        f"{resultado['online_omitidos']} ya estaban cargados, "
        f"{resultado['offline_cargados']} offline cargados."
    )


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        sys.exit(1)
