-- Esquema inicial — Monitoreo de Temperaturas V2
-- Todas las fechas se guardan en UTC (TIMESTAMPTZ); la conversion a hora local
-- se hace en la capa de consulta/dashboard, no aqui.

-- Arbol de agrupacion para el sidebar del dashboard (cliente -> ubicacion -> ...).
-- Profundidad libre: un servidor puede colgar de cualquier nivel (ver 'grupo'
-- en inventario_servidores.yaml, ej. "Quantum" o "AbInBev/Zacatecas").
-- 'orden' refleja la posicion en inventario_servidores.yaml (lo recalcula la
-- ingesta en cada corrida) -- el arbol del dashboard NO ordena alfabetico.
CREATE TABLE grupos (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,
    grupo_padre_id  INTEGER REFERENCES grupos(id),
    orden           INTEGER NOT NULL DEFAULT 0,
    UNIQUE (nombre, grupo_padre_id)
);

CREATE TABLE servidores (
    id                SERIAL PRIMARY KEY,
    nombre            VARCHAR(50) NOT NULL UNIQUE,
    sistema_operativo VARCHAR(10) NOT NULL CHECK (sistema_operativo IN ('ubuntu', 'windows')),
    activo            BOOLEAN NOT NULL DEFAULT true,
    grupo_id          INTEGER REFERENCES grupos(id),
    orden             INTEGER NOT NULL DEFAULT 0,
    creado_en         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Una fila por sensor leido en cada lectura (formato largo).
-- Ej: (DEVELOP, 2026-10-01 14:00, cpu, Core_0, 45.0)
CREATE TABLE lecturas (
    id            BIGSERIAL PRIMARY KEY,
    servidor_id   INTEGER NOT NULL REFERENCES servidores(id),
    medido_en     TIMESTAMPTZ NOT NULL,
    componente    VARCHAR(10) NOT NULL CHECK (componente IN ('cpu', 'gpu')),
    sensor        VARCHAR(50) NOT NULL,
    temperatura_c NUMERIC(4,1) NOT NULL,
    UNIQUE (servidor_id, medido_en, sensor)
);

-- Acelera las consultas del dashboard/API (agregaciones por servidor y rango de fecha).
CREATE INDEX idx_lecturas_servidor_fecha ON lecturas (servidor_id, medido_en DESC);

-- Uso de disco por punto de montaje real (no tmpfs/overlay/devtmpfs/etc).
-- Tabla separada de 'lecturas' a propósito -- no es temperatura, no tiene
-- sentido forzarla en 'componente'/'temperatura_c'. Se guarda como serie de
-- tiempo igual que 'lecturas' aunque el dashboard hoy solo muestre el
-- ultimo valor -- deja la puerta abierta a una grafica historica despues.
CREATE TABLE uso_disco (
    id            BIGSERIAL PRIMARY KEY,
    servidor_id   INTEGER NOT NULL REFERENCES servidores(id),
    medido_en     TIMESTAMPTZ NOT NULL,
    volumen       VARCHAR(100) NOT NULL,  -- grupo LVM o disco fisico, ej "ubuntu-vg" o "/dev/sdb"
    punto_montaje VARCHAR(100) NOT NULL,  -- ej "/", "/home"
    usado_gb      NUMERIC(10,1) NOT NULL,
    total_gb      NUMERIC(10,1) NOT NULL,
    UNIQUE (servidor_id, medido_en, punto_montaje)
);

CREATE INDEX idx_uso_disco_servidor_fecha ON uso_disco (servidor_id, medido_en DESC);

-- Hardware (informativo, solo para mostrarse en el dashboard -- no afecta el
-- calculo del semaforo). Administrado a mano via db/gestionar_servidor.py;
-- la sincronizacion automatica de ingesta.py (sincronizar_todo) nunca escribe
-- aqui, solo conoce nombre/grupo/activo.
CREATE TABLE hardware_chassis (
    servidor_id  INTEGER PRIMARY KEY REFERENCES servidores(id) ON DELETE CASCADE,
    marca        VARCHAR(50),
    modelo       VARCHAR(100),
    numero_serie VARCHAR(50),
    so_version   VARCHAR(30),  -- version exacta del SO, ej "Ubuntu 22.04.5 LTS" (sistema_operativo en 'servidores' solo guarda la familia)
    garantia     VARCHAR(50)   -- texto libre: fecha de vencimiento, "NO SUPPORT", "SIN INFORMACION", etc.
);

CREATE TABLE hardware_cpu (
    servidor_id INTEGER PRIMARY KEY REFERENCES servidores(id) ON DELETE CASCADE,
    modelo      VARCHAR(100) NOT NULL,
    nucleos     INTEGER
);

CREATE TABLE hardware_gpu (
    servidor_id INTEGER PRIMARY KEY REFERENCES servidores(id) ON DELETE CASCADE,
    modelo      VARCHAR(100) NOT NULL,
    nucleos     INTEGER
);

CREATE TABLE hardware_ram (
    servidor_id   INTEGER PRIMARY KEY REFERENCES servidores(id) ON DELETE CASCADE,
    total_gb      INTEGER NOT NULL,
    velocidad_mhz INTEGER
);

-- Detalle por modulo fisico de RAM -- opcional, solo donde se consiguio
-- (requiere dmidecode con root, o un inventario fisico externo). Sin esto,
-- hardware_ram.total_gb sigue siendo suficiente para el dashboard.
CREATE TABLE hardware_dimms (
    id            SERIAL PRIMARY KEY,
    servidor_id   INTEGER NOT NULL REFERENCES servidores(id) ON DELETE CASCADE,
    slot          VARCHAR(30) NOT NULL,
    estado        VARCHAR(20),  -- ej "Good", "Degraded", tal cual lo reporta la fuente
    capacidad_mb  INTEGER NOT NULL,
    velocidad_mhz INTEGER
);

-- Un servidor puede tener varios discos (o un solo "volumen logico" si un
-- RAID por hardware esconde los discos fisicos reales -- ver 'raid' abajo).
CREATE TABLE discos (
    id          SERIAL PRIMARY KEY,
    servidor_id INTEGER NOT NULL REFERENCES servidores(id) ON DELETE CASCADE,
    marca       VARCHAR(50),
    modelo      VARCHAR(100) NOT NULL,
    tipo        VARCHAR(20) NOT NULL CHECK (tipo IN ('ssd', 'hdd', 'nvme', 'logico')),
    capacidad   VARCHAR(20) NOT NULL,  -- tal cual lo reporta el SO, ej "953.9G" -- evita errores de conversion de unidades
    transporte  VARCHAR(10)            -- sata/sas/nvme; puede quedar vacio si no se detecto
);

-- Un servidor puede tener mas de un arreglo (ej. RAID0 de boot + RAID1 de
-- datos), por eso NO es 1:1 como hardware_cpu/gpu/ram -- servidor_id se
-- repite si hace falta.
CREATE TABLE raid (
    id          SERIAL PRIMARY KEY,
    servidor_id INTEGER NOT NULL REFERENCES servidores(id) ON DELETE CASCADE,
    tipo        VARCHAR(20) NOT NULL CHECK (tipo IN ('ninguno', 'software', 'hardware', 'desconocido')),
    nivel       VARCHAR(20),
    descripcion TEXT
);

-- Umbrales de temperatura por servidor (verde/ambar/rojo). El fallback
-- generico para un servidor sin fila aqui vive en backend/main.py
-- (UMBRALES_DEFAULT) -- no es dato de ningun servidor en particular.
CREATE TABLE umbrales (
    servidor_id INTEGER NOT NULL REFERENCES servidores(id) ON DELETE CASCADE,
    componente  VARCHAR(10) NOT NULL CHECK (componente IN ('cpu', 'gpu')),
    verde_max   NUMERIC(4,1) NOT NULL,
    ambar_max   NUMERIC(4,1) NOT NULL,
    PRIMARY KEY (servidor_id, componente)
);

-- Registro de que archivos ya se cargaron a la BD (online y offline).
-- Permite al modulo de ingesta saber que esta pendiente y evitar cargar
-- el mismo archivo dos veces (UNIQUE sobre servidor_id + nombre_archivo).
CREATE TABLE archivos_ingeridos (
    id             SERIAL PRIMARY KEY,
    servidor_id    INTEGER NOT NULL REFERENCES servidores(id),
    nombre_archivo VARCHAR(255) NOT NULL,
    origen         VARCHAR(10) NOT NULL CHECK (origen IN ('online', 'offline')),
    filas_cargadas INTEGER NOT NULL,
    cargado_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (servidor_id, nombre_archivo)
);
