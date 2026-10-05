"""
Extrae el inventario de hardware de ESTE servidor (chasis, CPU, GPU, RAM +
DIMMs, discos, RAID por software) y lo guarda en "<hostname>.json", en el
directorio actual.

Uso: sudo python3 extraer_hardware.py
(sudo hace falta para leer el detalle de RAM por dmidecode -- sin root, ese
bloque simplemente queda vacio, el resto del reporte sale igual.)

Solo lectura: no instala nada, no modifica el servidor. No intenta leer el
RAID por hardware (necesitaria storcli/perccli/ssacli, que no se instalan).

El .json resultante se sube a mano (o se manda por donde sea) a quien
administre la base de datos central -- ver
db/gestionar_servidor.py importar <archivo.json>.
"""
import json
import re
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def ejecutar(comando):
    try:
        resultado = subprocess.run(comando, shell=True, capture_output=True, text=True, timeout=15)
        return resultado.stdout.strip()
    except Exception:
        return ""


def es_root():
    return ejecutar("id -u") == "0"


# ─── Chasis ──────────────────────────────────────────────────────────────────
def leer_chasis():
    chasis = {"marca": None, "modelo": None, "numero_serie": None, "so_version": None}

    chasis["marca"] = ejecutar("cat /sys/class/dmi/id/sys_vendor") or None
    chasis["modelo"] = ejecutar("cat /sys/class/dmi/id/product_name") or None
    # product_serial casi siempre requiere root -- dmidecode -s system-serial-number
    # es equivalente y tambien lo requiere, se deja como intento adicional.
    serie = ejecutar("cat /sys/class/dmi/id/product_serial 2>/dev/null")
    if not serie or "Permission denied" in serie:
        serie = ejecutar("dmidecode -s system-serial-number 2>/dev/null")
    chasis["numero_serie"] = serie or None

    pretty_name = ejecutar("grep PRETTY_NAME /etc/os-release | cut -d'\"' -f2")
    chasis["so_version"] = pretty_name or None

    return chasis


# ─── CPU ─────────────────────────────────────────────────────────────────────
def leer_cpu():
    salida = ejecutar("lscpu -J")
    datos = {}
    try:
        for entrada in json.loads(salida)["lscpu"]:
            datos[entrada["field"].rstrip(":")] = entrada["data"]
    except Exception:
        # Fallback si esta version de lscpu no soporta -J
        salida = ejecutar("lscpu")
        for linea in salida.splitlines():
            if ":" in linea:
                clave, _, valor = linea.partition(":")
                datos[clave.strip()] = valor.strip()

    modelo = datos.get("Model name") or datos.get("Nombre del modelo")
    if modelo:
        modelo = re.sub(r"\s*\((R|TM)\)", "", modelo).strip()
    sockets = datos.get("Socket(s)") or datos.get("Sockets")
    nucleos_por_socket = datos.get("Core(s) per socket") or datos.get("Nucleos por socket")

    try:
        sockets = int(sockets)
    except (TypeError, ValueError):
        sockets = 1
    try:
        nucleos_por_socket = int(nucleos_por_socket)
    except (TypeError, ValueError):
        nucleos_por_socket = None

    return {
        "modelo": f"{sockets}x {modelo}" if sockets > 1 and modelo else modelo,
        "sockets": sockets,
        "nucleos_por_socket": nucleos_por_socket,
        "nucleos_totales": (nucleos_por_socket * sockets) if nucleos_por_socket else None,
    }


# ─── GPU ─────────────────────────────────────────────────────────────────────
def leer_gpu():
    if not ejecutar("which nvidia-smi"):
        return []
    salida = ejecutar("nvidia-smi --query-gpu=name --format=csv,noheader")
    return [{"modelo": linea.strip()} for linea in salida.splitlines() if linea.strip()]


# ─── RAM (total + DIMMs, requiere root para el detalle) ─────────────────────
def leer_ram():
    ram = {"total_gb": None, "velocidad_mhz": None, "dimms": []}

    total_bytes = ejecutar("cat /proc/meminfo | grep MemTotal | awk '{print $2}'")
    if total_bytes:
        try:
            ram["total_gb"] = round(int(total_bytes) / 1024 / 1024)
        except ValueError:
            pass

    salida = ejecutar("dmidecode -t memory 2>/dev/null")
    if not salida or "Permission denied" in salida or "dmidecode: command not found" in salida:
        return ram

    dimms = []
    velocidades = []
    for bloque in salida.split("Memory Device"):
        if "Size:" not in bloque:
            continue
        tamano = re.search(r"Size:\s*(.+)", bloque)
        if not tamano or "No Module Installed" in tamano.group(1):
            continue

        locator = re.search(r"\n\s*Locator:\s*(.+)", bloque)
        estado = re.search(r"Configured Memory Speed:\s*(.+)", bloque) or re.search(r"Speed:\s*(.+)", bloque)
        tamano_valor = tamano.group(1).strip()

        capacidad_mb = None
        m = re.match(r"(\d+)\s*(MB|GB)", tamano_valor)
        if m:
            capacidad_mb = int(m.group(1)) * (1024 if m.group(2) == "GB" else 1)

        velocidad_mhz = None
        if estado:
            vm = re.match(r"(\d+)\s*MT/s|(\d+)\s*MHz", estado.group(1).strip())
            if vm:
                velocidad_mhz = int(vm.group(1) or vm.group(2))
                velocidades.append(velocidad_mhz)

        dimms.append({
            "slot": locator.group(1).strip() if locator else "?",
            "estado": "Good",  # dmidecode no reporta salud del modulo, solo que esta instalado
            "capacidad_mb": capacidad_mb,
            "velocidad_mhz": velocidad_mhz,
        })

    ram["dimms"] = dimms
    if velocidades:
        ram["velocidad_mhz"] = max(set(velocidades), key=velocidades.count)  # la mas comun

    return ram


# ─── Discos ──────────────────────────────────────────────────────────────────
def leer_discos():
    salida = ejecutar("lsblk -d -o NAME,MODEL,SIZE,TYPE,TRAN,ROTA -J")
    discos = []
    try:
        for d in json.loads(salida)["blockdevices"]:
            if d.get("type") != "disk":
                continue
            rota = d.get("rota")
            tipo = "hdd" if rota in (True, "1") else "ssd"
            discos.append({
                "marca": None,
                "modelo": (d.get("model") or d.get("name") or "").strip(),
                "tipo": tipo,
                "capacidad": d.get("size"),
                "transporte": d.get("tran"),
            })
    except Exception:
        pass
    return discos


# ─── RAID por software (best-effort, sin herramientas de fabricante) ────────
def leer_raid_software():
    salida = ejecutar("cat /proc/mdstat 2>/dev/null")
    arreglos = []
    for linea in salida.splitlines():
        m = re.match(r"(md\d+)\s*:\s*active\s*(raid\d+)", linea)
        if m:
            arreglos.append({"tipo": "software", "nivel": m.group(2).upper(), "descripcion": linea.strip()})
    return arreglos


def main():
    hostname = socket.gethostname()
    reporte = {
        "hostname": hostname,
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "corrido_como_root": es_root(),
        "chasis": leer_chasis(),
        "cpu": leer_cpu(),
        "gpu": leer_gpu(),
        "ram": leer_ram(),
        "discos": leer_discos(),
        "raid_software": leer_raid_software(),
    }

    archivo = Path(f"{hostname}.json")
    archivo.write_text(json.dumps(reporte, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Reporte guardado en: {archivo.resolve()}")
    if not reporte["corrido_como_root"]:
        print("AVISO: no se corrio como root -- 'ram.dimms' y 'chasis.numero_serie' probablemente vinieron vacios.")
        print("       Corre con 'sudo python3 extraer_hardware.py' para obtener ese detalle.")
    if not reporte["gpu"]:
        print("Sin GPU detectada (o nvidia-smi no esta instalado) -- revisa si es correcto para este servidor.")
    print("RAID por hardware (si lo hay) NO se intento leer -- necesitaria instalar storcli/perccli/ssacli.")


if __name__ == "__main__":
    main()
