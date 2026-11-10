"""
Parseo de salidas de 'sensors'/'nvidia-smi' compartido entre
backend/ssh_lectura_directa.py y relay/leer_companero.py (funcionalidad
"Tiempo Real"). Ambos corren Python en una maquina con este mismo repo
clonado (DEVELOP y cada gateway respectivamente), asi que aqui SI conviene
compartir el modulo en vez de duplicarlo -- a diferencia de
colector_ubuntu/monitor.py, que corre en cada servidor monitoreado por
separado y no es importable desde el backend/gateway.

parsear_cpu_sensors y parsear_gpu son copia deliberada de
colector_ubuntu/monitor.py (mismo criterio de parseo, para no interpretar
distinto la misma salida de 'sensors'/'nvidia-smi') -- si ese formato
cambia ahi, revisar tambien aqui.
"""

COMANDO_WHICH_SENSORS = "which sensors"
COMANDO_SENSORS = "sensors"
COMANDO_WHICH_NVIDIA_SMI = "which nvidia-smi"
COMANDO_NVIDIA_SMI = "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits"

# RAM/Swap "en vivo" (boton Tiempo Real) -- /proc/meminfo en vez de 'free' para
# no depender de un paquete externo (ya es el mismo criterio que
# COMANDO_THERMAL_ZONES_SSH: leer directo el pseudo-filesystem del kernel).
COMANDO_MEMINFO_SSH = "cat /proc/meminfo"

# Variante por SSH (exec_command) de la deteccion de thermal zones que hace
# colector_ubuntu/monitor.py sobre archivos locales -- aqui no hay acceso a
# archivos locales, solo a lo que el comando remoto imprima.
COMANDO_THERMAL_ZONES_SSH = (
    "for z in /sys/class/thermal/thermal_zone*/; do "
    "n=$(basename \"$z\" | tr -dc '0-9'); "
    "echo \"$(cat \"${z}type\" 2>/dev/null)_$n:$(cat \"${z}temp\" 2>/dev/null)\"; "
    "done"
)


def parsear_cpu_sensors(salida_sensors):
    """
    No filtra por nombre de etiqueta (Core/Package son de Intel/coretemp;
    otros chips como k10temp de AMD usan Tctl/Tccd). En vez de eso, valida
    que el valor termine en "C"/"°C" -- asi reconoce cualquier chip de
    temperatura, y evita falsos positivos de lineas de ventilador (RPM) o
    voltaje (V).
    """
    temperaturas = {}
    chip_actual = ""
    for linea in salida_sensors.splitlines():
        linea_stripped = linea.strip()
        if not linea_stripped:
            chip_actual = ""
            continue
        if ":" not in linea_stripped:
            chip_actual = linea_stripped
            continue

        partes = linea.split(":")
        if len(partes) != 2:
            continue
        valores = partes[1].strip().split()
        if not valores:
            continue
        valor_crudo = valores[0]
        if not valor_crudo.endswith(("°C", "C")):
            continue

        nombre = partes[0].strip()
        valor_str = valor_crudo.replace("+", "").replace("°C", "").replace("C", "")
        try:
            valor = round(float(valor_str), 1)
        except ValueError:
            continue

        if nombre in temperaturas:
            nombre = f"{chip_actual}_{nombre}" if chip_actual else f"{nombre}_2"
        temperaturas[nombre] = valor
    return temperaturas


def parsear_cpu_thermal_zones_ssh(salida):
    """Espera lineas 'tipo_N:temp_miligrados', una por thermal zone (ver
    COMANDO_THERMAL_ZONES_SSH)."""
    temperaturas = {}
    for linea in salida.splitlines():
        if ":" not in linea:
            continue
        nombre, _, crudo = linea.partition(":")
        try:
            temperaturas[nombre] = round(int(crudo.strip()) / 1000, 1)
        except ValueError:
            continue
    return temperaturas


def parsear_gpu(salida_nvidia):
    gpus = {}
    for i, linea in enumerate(salida_nvidia.splitlines()):
        try:
            gpus[f"GPU_{i}"] = round(float(linea.strip()), 1)
        except ValueError:
            pass
    return gpus


def parsear_meminfo(salida):
    """
    Parsea 'cat /proc/meminfo' a MB. Todos los valores del archivo vienen en
    kB (aunque diga "kB" el kernel siempre usa 1024, no 1000).

    Replica el desglose que muestra 'htop' en su barra de memoria (usado/
    buffers/cache) en vez de solo un % -- MemAvailable (kernel >= 3.14) ya
    hace ese calculo por nosotros para el % real de uso, pero para pintar los
    3 segmentos de la barra se necesitan los componentes por separado.
    """
    valores = {}
    for linea in salida.splitlines():
        if ":" not in linea:
            continue
        nombre, _, resto = linea.partition(":")
        crudo = resto.strip().split()
        if not crudo:
            continue
        try:
            valores[nombre.strip()] = int(crudo[0])
        except ValueError:
            continue

    total_kb = valores.get("MemTotal")
    if not total_kb:
        return None

    libre_kb = valores.get("MemFree", 0)
    buffers_kb = valores.get("Buffers", 0)
    # Cached + SReclaimable (slab reclamable, ej. cache de metadatos de
    # filesystem) menos Shmem -- Shmem ya esta incluido en Cached por el
    # kernel pero es memoria "en uso" (tmpfs/shm), no cache liberable; mismo
    # ajuste que hace htop para no contarla dos veces ni como "cache" libre.
    cache_kb = valores.get("Cached", 0) + valores.get("SReclaimable", 0) - valores.get("Shmem", 0)
    cache_kb = max(cache_kb, 0)

    disponible_kb = valores.get("MemAvailable")
    if disponible_kb is None:
        disponible_kb = libre_kb + buffers_kb + cache_kb
    usado_kb = max(total_kb - disponible_kb, 0)

    swap_total_kb = valores.get("SwapTotal", 0)
    swap_libre_kb = valores.get("SwapFree", 0)
    swap_usado_kb = max(swap_total_kb - swap_libre_kb, 0)

    def a_mb(kb):
        return round(kb / 1024, 1)

    return {
        "total_mb": a_mb(total_kb),
        "usado_mb": a_mb(usado_kb),
        "buffers_mb": a_mb(buffers_kb),
        "cache_mb": a_mb(cache_kb),
        "libre_mb": a_mb(max(total_kb - usado_kb - buffers_kb - cache_kb, 0)),
        "porcentaje": round(usado_kb / total_kb * 100, 1),
        "swap_total_mb": a_mb(swap_total_kb),
        "swap_usado_mb": a_mb(swap_usado_kb),
        "swap_porcentaje": round(swap_usado_kb / swap_total_kb * 100, 1) if swap_total_kb else 0,
    }
