-- Esquema inicial — Monitoreo de Temperaturas V2
-- Todas las fechas se guardan en UTC (TIMESTAMPTZ); la conversion a hora local
-- se hace en la capa de consulta/dashboard, no aqui.

-- Arbol de agrupacion para el sidebar del dashboard (cliente -> ubicacion -> ...).
-- Profundidad libre: un servidor puede colgar de cualquier nivel (ver 'grupo'
-- en inventario_servidores.yaml, ej. "Quantum" o "AbInBev/Zacatecas").
CREATE TABLE grupos (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,
    grupo_padre_id  INTEGER REFERENCES grupos(id),
    UNIQUE (nombre, grupo_padre_id)
);

CREATE TABLE servidores (
    id                SERIAL PRIMARY KEY,
    nombre            VARCHAR(50) NOT NULL UNIQUE,
    sistema_operativo VARCHAR(10) NOT NULL CHECK (sistema_operativo IN ('ubuntu', 'windows')),
    activo            BOOLEAN NOT NULL DEFAULT true,
    grupo_id          INTEGER REFERENCES grupos(id),
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
