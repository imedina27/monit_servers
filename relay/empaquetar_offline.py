"""
Empaqueta en un .zip todo lo que hay que llevarse de este hub en la proxima
visita al sitio: las lecturas propias del colector local, mas lo que el
relay ya recolecto de sus companeros. Pensado para sitios 100% offline (ej.
AbInBev), donde no hay otra forma de sacar los datos mas que a mano.

Uso (correr en el propio hub, ej. QLYMSPROD01):
    python3 empaquetar_offline.py [nombre_de_este_hub] [nombre_del_sitio]

Sin argumentos usa HUB_DEFAULT/SITIO_DEFAULT (ver mas abajo). Para otro sitio,
pasa ambos argumentos:

Ej.:
    python3 empaquetar_offline.py QLYMSPROD01 AbInBev

Genera "relay_<nombre_del_sitio>_<ddmmaa>.zip" en el directorio actual, con una
subcarpeta por cada nombre (este hub + cada companero que ya tenga datos en
relay_entrante/):

    relay_AbInBev_131026.zip
      |- QLYMSPROD01/   (lo que genero el colector local de este servidor)
      |- QLYMSPROD02/   (lo que el relay ya recolecto de este companero)

Al terminar, verifica la integridad del .zip y ofrece borrar los .csv
originales (los que ya quedaron adentro) -- pide confirmacion explicita
antes de borrar nada. El .zip resultante tiene la misma estructura por
carpeta que ya espera ingesta/pendientes_offline/ en la maquina central
(un nombre de servidor por carpeta), asi que al llegar solo hace falta
descomprimirlo ahi (o subir cada carpeta con scripts/cargar_offline_remoto.py).
"""
import configparser
import datetime
import os
import sys
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)

# Hub/sitio por defecto cuando se corre sin argumentos -- editar aqui si este
# hub se reasigna a otro servidor/sitio de forma permanente.
HUB_DEFAULT = "QLYMSPROD01"
SITIO_DEFAULT = "AbInBev"


def cargar_config(ruta):
    config = configparser.ConfigParser()
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"No se encontro el archivo de configuracion: {ruta}")
    config.read(ruta, encoding="utf-8")
    return config


def directorio_colector_local():
    """Ruta real donde el colector de ESTE servidor deja sus .csv (lecturas y disco)."""
    config = cargar_config(os.path.join(PROJECT_DIR, "colector_ubuntu", "config.ini"))
    return config["almacenamiento"]["directorio_salida"]


def directorio_relay_entrante():
    """Carpeta donde el relay deja lo que ya recolecto de cada companero, por nombre."""
    config = cargar_config(os.path.join(BASE_DIR, "config.ini"))
    ruta = config["almacenamiento"]["directorio_entrante"]
    return ruta if os.path.isabs(ruta) else os.path.join(BASE_DIR, ruta)


def archivos_csv(directorio):
    if not os.path.isdir(directorio):
        return []
    return sorted(
        os.path.join(directorio, f) for f in os.listdir(directorio) if f.endswith(".csv")
    )


def main():
    if len(sys.argv) == 1:
        nombre_hub, nombre_sitio = HUB_DEFAULT, SITIO_DEFAULT
    elif len(sys.argv) == 3:
        nombre_hub, nombre_sitio = sys.argv[1], sys.argv[2]
    else:
        print(f"Uso: python3 {sys.argv[0]} [nombre_de_este_hub] [nombre_del_sitio]", file=sys.stderr)
        print("Ej.: python3 empaquetar_offline.py QLYMSPROD01 AbInBev", file=sys.stderr)
        print(f"Sin argumentos usa el default: {HUB_DEFAULT} {SITIO_DEFAULT}", file=sys.stderr)
        sys.exit(1)

    # Cada entrada: (nombre_de_carpeta_en_el_zip, lista_de_rutas_a_archivos_.csv)
    entradas = []

    dir_propio = directorio_colector_local()
    entradas.append((nombre_hub, archivos_csv(dir_propio)))

    dir_entrante = directorio_relay_entrante()
    companeros = []
    if os.path.isdir(dir_entrante):
        companeros = sorted(
            d for d in os.listdir(dir_entrante) if os.path.isdir(os.path.join(dir_entrante, d))
        )
    for companero in companeros:
        archivos = archivos_csv(os.path.join(dir_entrante, companero))
        if archivos:  # omite carpetas vacias (ej. restos de pruebas, companero sin datos aun)
            entradas.append((companero, archivos))

    total_archivos = sum(len(archivos) for _, archivos in entradas)
    if total_archivos == 0:
        print("No hay archivos .csv que empaquetar (ni propios ni de companeros). Nada que hacer.")
        return

    fecha = datetime.date.today().strftime("%d%m%y")
    nombre_zip = f"relay_{nombre_sitio}_{fecha}.zip"
    ruta_zip = os.path.join(os.getcwd(), nombre_zip)

    print(f"Empaquetando en {ruta_zip}:")
    with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for nombre_carpeta, archivos in entradas:
            print(f"  {nombre_carpeta}/: {len(archivos)} archivo(s)")
            for archivo in archivos:
                zf.write(archivo, arcname=f"{nombre_carpeta}/{os.path.basename(archivo)}")

    # Verificacion automatica de integridad -- aparte de que el usuario revise
    # el .zip a mano, esto confirma que no quedo corrupto antes de ofrecer borrar.
    with zipfile.ZipFile(ruta_zip) as zf:
        malo = zf.testzip()
    if malo is not None:
        print(f"\nERROR: el .zip quedo corrupto en '{malo}'. No se borra nada, revisa antes de continuar.", file=sys.stderr)
        sys.exit(1)

    print(f"\n.zip creado y verificado: {ruta_zip} ({total_archivos} archivo(s) en total)")
    print("Revisalo (ej. copialo a tu USB y ábrelo) antes de confirmar el borrado.")

    confirmacion = input(
        "\nEscribe 'si' para borrar los .csv originales que ya quedaron en el .zip: "
    ).strip().lower()
    if confirmacion != "si":
        print("Cancelado -- los .csv originales se quedan donde estaban.")
        return

    borrados = 0
    for _, archivos in entradas:
        for archivo in archivos:
            os.remove(archivo)
            borrados += 1
    print(f"{borrados} archivo(s) original(es) borrados.")


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        sys.exit(1)
