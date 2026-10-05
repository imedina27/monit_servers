import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_DIR / ".env")

USO = """Uso: pipenv run python db/gestionar_servidor.py <accion> [nombre|archivo.json]

Acciones:
  hardware <nombre>     Da de alta/modifica CPU, GPU, RAM, discos y RAID de un servidor (interactivo).
  umbrales <nombre>     Da de alta/modifica los umbrales de temperatura (verde/ambar/rojo).
  baja <nombre>         Elimina un servidor de Postgres (lecturas, hardware, umbrales, todo).
  importar <archivo.json>  Carga el reporte de scripts/extraer_hardware.py (sin preguntar nada).

Si no indicas <nombre>, se te deja elegir entre los servidores existentes.
El servidor debe existir ya en Postgres (agregalo primero a
inventario_servidores.yaml y corre la ingesta una vez) -- este script no
crea servidores nuevos en la tabla 'servidores', solo administra su
hardware/umbrales o lo da de baja por completo.
"""


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

    eleccion = input("Elige el numero del servidor: ").strip()
    try:
        return filas[int(eleccion) - 1][1]
    except (ValueError, IndexError):
        print("Opcion invalida.")
        sys.exit(1)


def obtener_servidor_id(conn, nombre):
    with conn.cursor() as cur:
        cur.execute("SELECT id, grupo_id FROM servidores WHERE nombre = %s", (nombre,))
        fila = cur.fetchone()
    if fila is None:
        print(f"No existe ningun servidor llamado '{nombre}' en Postgres.")
        print("Agregalo primero a inventario_servidores.yaml y corre la ingesta (o el boton 'Actualizar') una vez.")
        sys.exit(1)
    return fila


def pedir(mensaje, actual=None, opcional=True):
    """input() con valor actual mostrado; Enter en blanco conserva 'actual'."""
    sufijo = f" [{actual}]" if actual is not None else (" [vacio]" if opcional else "")
    respuesta = input(f"{mensaje}{sufijo}: ").strip()
    return respuesta if respuesta else actual


def pedir_entero(mensaje, actual=None):
    while True:
        respuesta = pedir(mensaje, actual)
        if respuesta in (None, ""):
            return None
        try:
            return int(respuesta)
        except ValueError:
            print("  Debe ser un numero entero (o Enter para dejarlo vacio).")


# ─── Accion: hardware ──────────────────────────────────────────────────────
def cmd_hardware(conn, nombre):
    servidor_id, _ = obtener_servidor_id(conn, nombre)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT marca, modelo, numero_serie, so_version, garantia FROM hardware_chassis WHERE servidor_id = %s",
            (servidor_id,),
        )
        chasis_actual = cur.fetchone()
        cur.execute("SELECT modelo, nucleos FROM hardware_cpu WHERE servidor_id = %s", (servidor_id,))
        cpu_actual = cur.fetchone()
        cur.execute("SELECT modelo, nucleos FROM hardware_gpu WHERE servidor_id = %s", (servidor_id,))
        gpu_actual = cur.fetchone()
        cur.execute("SELECT total_gb, velocidad_mhz FROM hardware_ram WHERE servidor_id = %s", (servidor_id,))
        ram_actual = cur.fetchone()
        cur.execute(
            "SELECT slot, estado, capacidad_mb, velocidad_mhz FROM hardware_dimms WHERE servidor_id = %s ORDER BY id",
            (servidor_id,),
        )
        dimms_actuales = cur.fetchall()
        cur.execute(
            "SELECT marca, modelo, tipo, capacidad, transporte FROM discos WHERE servidor_id = %s ORDER BY id",
            (servidor_id,),
        )
        discos_actuales = cur.fetchall()
        cur.execute("SELECT tipo, nivel, descripcion FROM raid WHERE servidor_id = %s ORDER BY id", (servidor_id,))
        raid_actuales = cur.fetchall()

    print(f"\n=== Hardware de '{nombre}' ===")
    print("(Enter en cualquier campo conserva el valor actual)\n")

    print("-- Chasis fisico --")
    chasis_marca = pedir("Marca", chasis_actual[0] if chasis_actual else None)
    chasis_modelo = pedir("Modelo", chasis_actual[1] if chasis_actual else None)
    chasis_serie = pedir("Numero de serie", chasis_actual[2] if chasis_actual else None)
    chasis_so = pedir("Version de SO (ej. Ubuntu 22.04.5 LTS)", chasis_actual[3] if chasis_actual else None)
    chasis_garantia = pedir("Garantia (fecha, 'NO SUPPORT', etc.)", chasis_actual[4] if chasis_actual else None)
    if any((chasis_marca, chasis_modelo, chasis_serie, chasis_so, chasis_garantia)):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO hardware_chassis (servidor_id, marca, modelo, numero_serie, so_version, garantia)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (servidor_id) DO UPDATE
                       SET marca = EXCLUDED.marca, modelo = EXCLUDED.modelo,
                           numero_serie = EXCLUDED.numero_serie, so_version = EXCLUDED.so_version,
                           garantia = EXCLUDED.garantia""",
                (servidor_id, chasis_marca, chasis_modelo, chasis_serie, chasis_so, chasis_garantia),
            )

    print("\n-- CPU --")
    cpu_modelo = pedir("Modelo de CPU", cpu_actual[0] if cpu_actual else None, opcional=False)
    cpu_nucleos = pedir_entero("Nucleos de CPU", cpu_actual[1] if cpu_actual else None)
    if not cpu_modelo:
        print("  Modelo de CPU es obligatorio, no se guardo nada de CPU.")
    else:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO hardware_cpu (servidor_id, modelo, nucleos) VALUES (%s, %s, %s)
                   ON CONFLICT (servidor_id) DO UPDATE SET modelo = EXCLUDED.modelo, nucleos = EXCLUDED.nucleos""",
                (servidor_id, cpu_modelo, cpu_nucleos),
            )

    print("\n-- GPU (deja modelo en blanco si este servidor no tiene GPU) --")
    gpu_modelo = pedir("Modelo de GPU", gpu_actual[0] if gpu_actual else None)
    if gpu_modelo:
        gpu_nucleos = pedir_entero("Nucleos de GPU", gpu_actual[1] if gpu_actual else None)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO hardware_gpu (servidor_id, modelo, nucleos) VALUES (%s, %s, %s)
                   ON CONFLICT (servidor_id) DO UPDATE SET modelo = EXCLUDED.modelo, nucleos = EXCLUDED.nucleos""",
                (servidor_id, gpu_modelo, gpu_nucleos),
            )
    elif gpu_actual:
        if pedir("Se borro el modelo -- confirma eliminar la GPU de este servidor (si/no)", "no") == "si":
            with conn.cursor() as cur:
                cur.execute("DELETE FROM hardware_gpu WHERE servidor_id = %s", (servidor_id,))

    print("\n-- RAM --")
    ram_gb = pedir_entero("Total de RAM (GB)", ram_actual[0] if ram_actual else None)
    ram_velocidad = pedir_entero("Velocidad de RAM (MHz)", ram_actual[1] if ram_actual else None)
    if ram_gb is not None:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO hardware_ram (servidor_id, total_gb, velocidad_mhz) VALUES (%s, %s, %s)
                   ON CONFLICT (servidor_id) DO UPDATE
                       SET total_gb = EXCLUDED.total_gb, velocidad_mhz = EXCLUDED.velocidad_mhz""",
                (servidor_id, ram_gb, ram_velocidad),
            )

    print("\n-- DIMMs (detalle por modulo fisico, opcional) --")
    if dimms_actuales:
        print("  DIMMs actuales:")
        for d in dimms_actuales:
            print(f"    - {d[0]}: {d[1] or 's/d'}, {d[2]}MB @ {d[3] or 's/d'}MHz")
    if pedir("Reemplazar la lista de DIMMs (si/no)", "no") == "si":
        nuevos_dimms = []
        print("  Agrega los DIMMs uno por uno. Deja 'slot' en blanco para terminar.")
        while True:
            slot = input("  Slot (ej. DIMM01, P1-DIMMC2, blanco para terminar): ").strip()
            if not slot:
                break
            estado = input("    Estado (ej. Good, Degraded, opcional): ").strip() or None
            capacidad_mb = None
            while capacidad_mb is None:
                try:
                    capacidad_mb = int(input("    Capacidad (MB, ej. 32768): ").strip())
                except ValueError:
                    print("    Debe ser un numero entero.")
            velocidad = input("    Velocidad (MHz, opcional): ").strip()
            velocidad = int(velocidad) if velocidad else None
            nuevos_dimms.append((slot, estado, capacidad_mb, velocidad))
        with conn.cursor() as cur:
            cur.execute("DELETE FROM hardware_dimms WHERE servidor_id = %s", (servidor_id,))
            for slot, estado, capacidad_mb, velocidad in nuevos_dimms:
                cur.execute(
                    """INSERT INTO hardware_dimms (servidor_id, slot, estado, capacidad_mb, velocidad_mhz)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (servidor_id, slot, estado, capacidad_mb, velocidad),
                )
        print(f"  {len(nuevos_dimms)} DIMM(s) guardado(s).")

    print("\n-- Discos --")
    if discos_actuales:
        print("  Discos actuales:")
        for d in discos_actuales:
            print(f"    - {d[0] or ''} {d[1]} ({d[2]}, {d[3]}, {d[4] or 's/d'})")
    if pedir("Reemplazar la lista de discos (si/no)", "no") == "si":
        nuevos_discos = []
        print("  Agrega los discos uno por uno. Deja 'modelo' en blanco para terminar.")
        while True:
            modelo = input("  Modelo de disco (blanco para terminar): ").strip()
            if not modelo:
                break
            marca = input("    Marca (opcional): ").strip() or None
            tipo = input("    Tipo (ssd/hdd/nvme/logico): ").strip().lower()
            while tipo not in ("ssd", "hdd", "nvme", "logico"):
                tipo = input("    Tipo invalido, usa ssd/hdd/nvme/logico: ").strip().lower()
            capacidad = input("    Capacidad (ej. 953.9G, 1.8T): ").strip()
            transporte = input("    Transporte (sata/sas/nvme, opcional): ").strip().lower() or None
            nuevos_discos.append((marca, modelo, tipo, capacidad, transporte))
        with conn.cursor() as cur:
            cur.execute("DELETE FROM discos WHERE servidor_id = %s", (servidor_id,))
            for marca, modelo, tipo, capacidad, transporte in nuevos_discos:
                cur.execute(
                    """INSERT INTO discos (servidor_id, marca, modelo, tipo, capacidad, transporte)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (servidor_id, marca, modelo, tipo, capacidad, transporte),
                )
        print(f"  {len(nuevos_discos)} disco(s) guardado(s).")

    print("\n-- RAID (un servidor puede tener varios arreglos, ej. RAID0 de boot + RAID1 de datos) --")
    if raid_actuales:
        print("  Arreglos actuales:")
        for r in raid_actuales:
            print(f"    - {r[0]}, nivel {r[1] or 's/d'}: {r[2] or ''}")
    if pedir("Reemplazar la lista de arreglos RAID (si/no)", "no") == "si":
        nuevos_raid = []
        print("  Agrega los arreglos uno por uno. Deja 'tipo' en blanco para terminar.")
        tipos_validos = ("ninguno", "software", "hardware", "desconocido")
        while True:
            tipo_raid = input(f"  Tipo ({'/'.join(tipos_validos)}, blanco para terminar): ").strip().lower()
            if not tipo_raid:
                break
            while tipo_raid not in tipos_validos:
                tipo_raid = input(f"    Tipo invalido, usa {'/'.join(tipos_validos)}: ").strip().lower()
            nivel_raid = input("    Nivel (ej. RAID1, RAID5, opcional): ").strip() or None
            descripcion_raid = input("    Descripcion (opcional): ").strip() or None
            nuevos_raid.append((tipo_raid, nivel_raid, descripcion_raid))
        with conn.cursor() as cur:
            cur.execute("DELETE FROM raid WHERE servidor_id = %s", (servidor_id,))
            for tipo_raid, nivel_raid, descripcion_raid in nuevos_raid:
                cur.execute(
                    "INSERT INTO raid (servidor_id, tipo, nivel, descripcion) VALUES (%s, %s, %s, %s)",
                    (servidor_id, tipo_raid, nivel_raid, descripcion_raid),
                )
        print(f"  {len(nuevos_raid)} arreglo(s) guardado(s).")

    conn.commit()
    print(f"\nHardware de '{nombre}' guardado.")


# ─── Accion: umbrales ──────────────────────────────────────────────────────
def cmd_umbrales(conn, nombre):
    servidor_id, _ = obtener_servidor_id(conn, nombre)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT componente, verde_max, ambar_max FROM umbrales WHERE servidor_id = %s",
            (servidor_id,),
        )
        actuales = {fila[0]: (fila[1], fila[2]) for fila in cur.fetchall()}

    print(f"\n=== Umbrales de '{nombre}' ===")
    print("(Deja ambos campos en blanco para quitar el override y usar el default generico)\n")

    for componente in ("cpu", "gpu"):
        actual = actuales.get(componente)
        etiqueta = "override actual" if actual else "sin override (usa el default)"
        print(f"-- {componente.upper()} ({etiqueta}) --")
        verde_max = pedir("  verde_max", actual[0] if actual else None)
        ambar_max = pedir("  ambar_max", actual[1] if actual else None)

        with conn.cursor() as cur:
            if verde_max is None and ambar_max is None:
                cur.execute(
                    "DELETE FROM umbrales WHERE servidor_id = %s AND componente = %s",
                    (servidor_id, componente),
                )
            else:
                cur.execute(
                    """INSERT INTO umbrales (servidor_id, componente, verde_max, ambar_max)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (servidor_id, componente) DO UPDATE
                           SET verde_max = EXCLUDED.verde_max, ambar_max = EXCLUDED.ambar_max""",
                    (servidor_id, componente, verde_max, ambar_max),
                )

    conn.commit()
    print(f"\nUmbrales de '{nombre}' guardados.")


# ─── Accion: importar ──────────────────────────────────────────────────────
def cmd_importar(conn, ruta_json):
    with open(ruta_json, encoding="utf-8") as f:
        datos = json.load(f)

    hostname = datos["hostname"]
    with conn.cursor() as cur:
        cur.execute("SELECT id, nombre FROM servidores WHERE LOWER(nombre) = LOWER(%s)", (hostname,))
        fila = cur.fetchone()
    if fila is None:
        print(f"No existe ningun servidor que coincida con el hostname '{hostname}' (de {ruta_json}).")
        sys.exit(1)
    servidor_id, nombre_real = fila
    print(f"Importando a '{nombre_real}' (id {servidor_id}) desde {ruta_json} ...")

    chasis = datos.get("chasis") or {}
    cpu = datos.get("cpu") or {}
    gpu = datos.get("gpu") or []
    ram = datos.get("ram") or {}
    discos = datos.get("discos") or []
    raid_software = datos.get("raid_software") or []

    with conn.cursor() as cur:
        # Chasis: COALESCE para no pisar con NULL un campo que el .json no
        # trajo (ej. numero_serie sin root), y 'garantia' nunca la toca este
        # importador -- el script no puede saberla, es dato administrativo.
        if any(chasis.get(k) for k in ("marca", "modelo", "numero_serie", "so_version")):
            cur.execute(
                """INSERT INTO hardware_chassis (servidor_id, marca, modelo, numero_serie, so_version)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (servidor_id) DO UPDATE
                       SET marca = COALESCE(EXCLUDED.marca, hardware_chassis.marca),
                           modelo = COALESCE(EXCLUDED.modelo, hardware_chassis.modelo),
                           numero_serie = COALESCE(EXCLUDED.numero_serie, hardware_chassis.numero_serie),
                           so_version = COALESCE(EXCLUDED.so_version, hardware_chassis.so_version)""",
                (servidor_id, chasis.get("marca"), chasis.get("modelo"), chasis.get("numero_serie"), chasis.get("so_version")),
            )
            print("  chasis: actualizado")

        if cpu.get("modelo"):
            cur.execute(
                """INSERT INTO hardware_cpu (servidor_id, modelo, nucleos) VALUES (%s, %s, %s)
                   ON CONFLICT (servidor_id) DO UPDATE SET modelo = EXCLUDED.modelo, nucleos = EXCLUDED.nucleos""",
                (servidor_id, cpu["modelo"], cpu.get("nucleos_totales")),
            )
            print("  cpu: actualizado")

        if gpu:
            modelos = sorted({g["modelo"] for g in gpu})
            modelo_gpu = f"{len(gpu)}x {modelos[0]}" if len(modelos) == 1 and len(gpu) > 1 else " + ".join(modelos)
            # Nucleos CUDA: el script no los puede saber (no vienen de nvidia-smi),
            # se conserva lo que ya hubiera cargado a mano.
            cur.execute("SELECT nucleos FROM hardware_gpu WHERE servidor_id = %s", (servidor_id,))
            fila_actual = cur.fetchone()
            nucleos_actuales = fila_actual[0] if fila_actual else None
            cur.execute(
                """INSERT INTO hardware_gpu (servidor_id, modelo, nucleos) VALUES (%s, %s, %s)
                   ON CONFLICT (servidor_id) DO UPDATE SET modelo = EXCLUDED.modelo""",
                (servidor_id, modelo_gpu, nucleos_actuales),
            )
            print(f"  gpu: actualizado ({modelo_gpu}) -- nucleos CUDA sin tocar")

        if ram.get("total_gb"):
            cur.execute("SELECT velocidad_mhz FROM hardware_ram WHERE servidor_id = %s", (servidor_id,))
            fila_actual = cur.fetchone()
            velocidad = ram.get("velocidad_mhz") or (fila_actual[0] if fila_actual else None)
            cur.execute(
                """INSERT INTO hardware_ram (servidor_id, total_gb, velocidad_mhz) VALUES (%s, %s, %s)
                   ON CONFLICT (servidor_id) DO UPDATE SET total_gb = EXCLUDED.total_gb, velocidad_mhz = EXCLUDED.velocidad_mhz""",
                (servidor_id, ram["total_gb"], velocidad),
            )
            print("  ram: actualizado")

        # DIMMs: solo se tocan si el .json SI trae detalle (corrio como root) --
        # si no, no se borra el detalle que ya hubiera de otra fuente.
        if ram.get("dimms"):
            cur.execute("DELETE FROM hardware_dimms WHERE servidor_id = %s", (servidor_id,))
            for d in ram["dimms"]:
                cur.execute(
                    """INSERT INTO hardware_dimms (servidor_id, slot, estado, capacidad_mb, velocidad_mhz)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (servidor_id, d["slot"], d.get("estado"), d.get("capacidad_mb"), d.get("velocidad_mhz")),
                )
            print(f"  dimms: {len(ram['dimms'])} modulo(s)")
        else:
            print("  dimms: el .json no trae detalle (no se corrio como root) -- se deja lo que ya habia")

        if discos:
            cur.execute("DELETE FROM discos WHERE servidor_id = %s", (servidor_id,))
            for d in discos:
                cur.execute(
                    """INSERT INTO discos (servidor_id, marca, modelo, tipo, capacidad, transporte)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (servidor_id, d.get("marca"), d["modelo"], d["tipo"], d["capacidad"], d.get("transporte")),
                )
            print(f"  discos: {len(discos)}")

        # RAID: solo se reemplazan las filas tipo 'software' (lo que este
        # script si puede confirmar via /proc/mdstat) -- un 'hardware'/
        # 'desconocido' cargado a mano se queda intacto.
        if raid_software:
            cur.execute("DELETE FROM raid WHERE servidor_id = %s AND tipo = 'software'", (servidor_id,))
            for r in raid_software:
                cur.execute(
                    "INSERT INTO raid (servidor_id, tipo, nivel, descripcion) VALUES (%s, %s, %s, %s)",
                    (servidor_id, r["tipo"], r.get("nivel"), r.get("descripcion")),
                )
            print(f"  raid (software): {len(raid_software)} arreglo(s)")

    conn.commit()
    print(f"\n'{nombre_real}' actualizado desde {ruta_json}.")


# ─── Accion: baja ──────────────────────────────────────────────────────────
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


def cmd_baja(conn, nombre):
    servidor_id, grupo_id = obtener_servidor_id(conn, nombre)

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM lecturas WHERE servidor_id = %s", (servidor_id,))
        n_lecturas = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM archivos_ingeridos WHERE servidor_id = %s", (servidor_id,))
        n_archivos = cur.fetchone()[0]

    print(f"\nEsto borrara PERMANENTEMENTE a '{nombre}' de la base de datos:")
    print(f"  - {n_lecturas} lecturas")
    print(f"  - {n_archivos} registros de archivos ya ingeridos")
    print("  - su hardware, discos, RAID y umbrales (si tenia)")
    print("Tambien quitalo de 'inventario_servidores.yaml' si es un retiro definitivo")
    print("(este script solo limpia Postgres, no toca el inventario).")
    confirmacion = input("Escribe 'si' para continuar: ").strip().lower()
    if confirmacion != "si":
        print("Cancelado.")
        return

    with conn.cursor() as cur:
        cur.execute("DELETE FROM archivos_ingeridos WHERE servidor_id = %s", (servidor_id,))
        cur.execute("DELETE FROM lecturas WHERE servidor_id = %s", (servidor_id,))
        # hardware_cpu/hardware_gpu/hardware_ram/discos/raid/umbrales tienen
        # ON DELETE CASCADE sobre servidores(id) -- se limpian solos.
        cur.execute("DELETE FROM servidores WHERE id = %s", (servidor_id,))
    conn.commit()
    print(f"'{nombre}' eliminado.")

    grupos_borrados = limpiar_grupos_vacios(conn, grupo_id)
    conn.commit()
    if grupos_borrados:
        print(f"Grupos vacios tambien eliminados: {', '.join(grupos_borrados)}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("hardware", "umbrales", "baja", "importar"):
        print(USO)
        sys.exit(1)

    accion = sys.argv[1]
    conn = conectar_db()

    if accion == "importar":
        if len(sys.argv) < 3:
            print(USO)
            sys.exit(1)
        cmd_importar(conn, sys.argv[2])
        conn.close()
        return

    nombre = sys.argv[2] if len(sys.argv) > 2 else elegir_servidor(conn)

    if accion == "hardware":
        cmd_hardware(conn, nombre)
    elif accion == "umbrales":
        cmd_umbrales(conn, nombre)
    elif accion == "baja":
        cmd_baja(conn, nombre)

    conn.close()


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        sys.exit(1)
