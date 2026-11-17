BEGIN;

CREATE TABLE IF NOT EXISTS usuarios (
    id BIGSERIAL PRIMARY KEY,
    usuario TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    creado_en BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS dispositivos (
    id BIGSERIAL PRIMARY KEY,
    mac TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    owner_id BIGINT REFERENCES usuarios(id),
    ip TEXT,
    rssi INTEGER,
    primera_conexion BIGINT NOT NULL,
    ultima_conexion BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS lecturas (
    id BIGSERIAL PRIMARY KEY,
    device_id BIGINT NOT NULL REFERENCES dispositivos(id) ON DELETE RESTRICT,
    ts BIGINT NOT NULL,
    temperatura DOUBLE PRECISION,
    nivel_agua DOUBLE PRECISION,
    turbidez DOUBLE PRECISION,
    ph DOUBLE PRECISION
);
ALTER TABLE lecturas ADD COLUMN IF NOT EXISTS turbidez DOUBLE PRECISION;
ALTER TABLE lecturas ADD COLUMN IF NOT EXISTS ph DOUBLE PRECISION;
CREATE INDEX IF NOT EXISTS idx_lecturas_dev_ts_id ON lecturas(device_id, ts DESC, id DESC);

CREATE TABLE IF NOT EXISTS intentos_login (
    ip TEXT PRIMARY KEY,
    cantidad INTEGER NOT NULL,
    desde BIGINT NOT NULL
);

COMMIT;
