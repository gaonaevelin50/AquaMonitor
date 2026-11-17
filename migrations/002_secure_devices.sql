-- Apply explicitly AFTER 001. Never run automatically on application startup.
BEGIN;
ALTER TABLE dispositivos ADD COLUMN public_id UUID UNIQUE;
ALTER TABLE dispositivos ADD COLUMN registration_id UUID UNIQUE;
ALTER TABLE dispositivos ADD COLUMN bloqueado BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE dispositivos ADD COLUMN recovery_until BIGINT;
-- MAC is metadata, not an identity or a proof of ownership.
ALTER TABLE dispositivos DROP CONSTRAINT IF EXISTS dispositivos_mac_key;
CREATE TABLE asignaciones_dispositivo (
 id BIGSERIAL PRIMARY KEY,
 device_id BIGINT NOT NULL REFERENCES dispositivos(id) ON DELETE RESTRICT,
 owner_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
 nombre TEXT NOT NULL CHECK(length(nombre) BETWEEN 1 AND 40),
 inicio BIGINT NOT NULL,
 fin BIGINT CHECK(fin IS NULL OR fin >= inicio),
 UNIQUE(id,device_id)
);
CREATE UNIQUE INDEX una_asignacion_activa ON asignaciones_dispositivo(device_id) WHERE fin IS NULL;
CREATE INDEX asignaciones_owner ON asignaciones_dispositivo(owner_id,id);
ALTER TABLE lecturas ADD COLUMN asignacion_id BIGINT;
ALTER TABLE lecturas ADD CONSTRAINT lectura_asignacion_fk FOREIGN KEY(asignacion_id,device_id)
 REFERENCES asignaciones_dispositivo(id,device_id) ON DELETE RESTRICT;
CREATE INDEX lecturas_asignacion_ts ON lecturas(asignacion_id,ts DESC,id DESC);
-- Deliberately NO backfill: historical ownership cannot be inferred.
CREATE TABLE credenciales_dispositivo (
 id BIGSERIAL PRIMARY KEY,
 device_id BIGINT NOT NULL REFERENCES dispositivos(id) ON DELETE RESTRICT,
 proposito TEXT NOT NULL CHECK(proposito IN ('config','medicion')),
 token_hash TEXT NOT NULL UNIQUE CHECK(length(token_hash)=64),
 generacion UUID NOT NULL,
 asignacion_id BIGINT,
 creado_en BIGINT NOT NULL,
 revocado_en BIGINT,
 UNIQUE(device_id,proposito,generacion),
 FOREIGN KEY(asignacion_id,device_id) REFERENCES asignaciones_dispositivo(id,device_id) ON DELETE RESTRICT,
 CHECK(proposito <> 'config' OR asignacion_id IS NULL)
);
CREATE UNIQUE INDEX una_credencial_activa ON credenciales_dispositivo(device_id,proposito) WHERE revocado_en IS NULL;
CREATE TABLE solicitudes_vinculacion (
 id UUID PRIMARY KEY,
 device_id BIGINT NOT NULL REFERENCES dispositivos(id) ON DELETE RESTRICT,
 code_hash TEXT NOT NULL UNIQUE,
 creado_en BIGINT NOT NULL,
 expira_en BIGINT NOT NULL,
 cerrada_en BIGINT,
 consumida_por BIGINT REFERENCES usuarios(id) ON DELETE RESTRICT,
 CHECK(expira_en > creado_en)
);
CREATE UNIQUE INDEX una_solicitud_activa ON solicitudes_vinculacion(device_id) WHERE cerrada_en IS NULL;
CREATE TABLE eventos_dispositivo (
 id BIGSERIAL PRIMARY KEY,
 device_id BIGINT NOT NULL REFERENCES dispositivos(id) ON DELETE RESTRICT,
 usuario_id BIGINT REFERENCES usuarios(id) ON DELETE RESTRICT,
 evento TEXT NOT NULL,
 ts BIGINT NOT NULL
);
CREATE TABLE limites_seguridad (
 clave TEXT PRIMARY KEY,
 ventana BIGINT NOT NULL,
 cantidad INTEGER NOT NULL CHECK(cantidad > 0)
);
CREATE TABLE sesiones_usuario (
 token_hash TEXT PRIMARY KEY,
 usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
 creado_en BIGINT NOT NULL,
 expira_en BIGINT NOT NULL,
 revocado_en BIGINT
);
CREATE INDEX sesiones_usuario_expira ON sesiones_usuario(expira_en);
CREATE TABLE aquamonitor_migraciones (version INTEGER PRIMARY KEY,aplicada_en TIMESTAMPTZ NOT NULL DEFAULT now());
INSERT INTO aquamonitor_migraciones(version) VALUES(2);
COMMIT;
