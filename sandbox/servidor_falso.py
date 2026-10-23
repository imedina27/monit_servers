"""
Servidor SSH falso (paramiko en modo servidor) para probar "Tiempo Real" SIN
Docker/WSL -- no hace falta ningun sistema Linux real, solo Python +
paramiko (ya es dependencia del proyecto). Responde a los mismos comandos
que arma backend/ssh_lectura_directa.py / relay/leer_companero.py
(ver comun/parseo_sensores.py) con datos de ejemplo cambiantes.

Pensado para que sandbox/levantar_sandbox.py levante 2-3 instancias de este
mismo servidor en distintos puertos de localhost (directo, gateway,
companero) -- ver sandbox/README.md. No pensado para usarse solo.
"""
import random
import socket
import threading

import paramiko

USUARIO = "monitor"
PASSWORD = "monitor"


def salida_sensors():
    t_pkg = random.randint(40, 55)
    t0 = random.randint(38, 53)
    t1 = random.randint(38, 53)
    return (
        "coretemp-isa-0000\n"
        "Adapter: ISA adapter\n"
        f"Package id 0:  +{t_pkg}.0°C  (high = +90.0°C, crit = +100.0°C)\n"
        f"Core 0:        +{t0}.0°C  (high = +90.0°C, crit = +100.0°C)\n"
        f"Core 1:        +{t1}.0°C  (high = +90.0°C, crit = +100.0°C)\n"
    )


def salida_nvidia_smi():
    return f"{random.randint(50, 70)}\n"


class _ServerInterfaceFalso(paramiko.ServerInterface):
    def __init__(self):
        self.evento_comando = threading.Event()
        self.comando = None

    def check_auth_password(self, username, password):
        if username == USUARIO and password == PASSWORD:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        self.comando = command.decode() if isinstance(command, bytes) else command
        self.evento_comando.set()
        return True


def _responder_comando(comando, con_gpu, ejecutor_extra):
    """Mismo set de comandos que usa ssh_lectura_directa.py/leer_companero.py
    (ver comun/parseo_sensores.py) -- devuelve (stdout, stderr, exit_code)."""
    if "which sensors" in comando:
        return "/usr/bin/sensors\n" + salida_sensors(), "", 0
    if comando.strip() == "sensors":
        return salida_sensors(), "", 0
    if "which nvidia-smi" in comando:
        return ("/usr/bin/nvidia-smi\n" if con_gpu else ""), "", 0
    if "nvidia-smi --query-gpu" in comando:
        return (salida_nvidia_smi() if con_gpu else ""), "", 0
    if ejecutor_extra is not None:
        return ejecutor_extra(comando)
    return "", f"[sandbox] comando no soportado: {comando}", 1


def _atender_cliente(conexion, clave_host, con_gpu, ejecutor_extra):
    """
    Un cliente SSH real (paramiko.SSHClient) abre un canal NUEVO por cada
    exec_command() sobre la MISMA conexion/transport -- ssh_lectura_directa.py
    y leer_companero.py hacen varias llamadas exec_command seguidas (which
    sensors, sensors, which nvidia-smi, nvidia-smi ...) en una sola sesion.
    Por eso aqui se atiende un loop de canales, no uno solo -- cerrar el
    transport tras el primer comando rompia la segunda llamada con EOFError.
    """
    transporte = None
    try:
        transporte = paramiko.Transport(conexion)
        transporte.add_server_key(clave_host)
        interfaz = _ServerInterfaceFalso()
        transporte.start_server(server=interfaz)

        while transporte.is_active():
            canal = transporte.accept(20)
            if canal is None:
                break
            if not interfaz.evento_comando.wait(10):
                break
            interfaz.evento_comando.clear()

            salida, error, codigo = _responder_comando(interfaz.comando, con_gpu, ejecutor_extra)
            if salida:
                canal.send(salida.encode("utf-8"))
            if error:
                canal.send_stderr(error.encode("utf-8"))
            canal.send_exit_status(codigo)
            canal.close()
    except Exception as e:
        print(f"[sandbox] error atendiendo conexion: {e}")
    finally:
        if transporte is not None:
            try:
                transporte.close()
            except Exception:
                pass


def servir(puerto, con_gpu=True, ejecutor_extra=None, etiqueta=""):
    """Bloqueante -- se espera correr en su propio hilo/proceso (ver
    levantar_sandbox.py). clave_host se genera una vez por instancia."""
    clave_host = paramiko.RSAKey.generate(2048)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", puerto))
    sock.listen(10)
    print(f"[sandbox] {etiqueta or 'servidor falso'} escuchando en 127.0.0.1:{puerto} (usuario={USUARIO}/{PASSWORD})")

    while True:
        conexion, _ = sock.accept()
        threading.Thread(
            target=_atender_cliente,
            args=(conexion, clave_host, con_gpu, ejecutor_extra),
            daemon=True,
        ).start()


if __name__ == "__main__":
    import sys
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 2203
    servir(puerto, con_gpu=True, etiqueta=f"puerto {puerto}")
