-- OPTIONAL diagnostics persistence only. Not required for safe core readings.
-- Prepared only: apply explicitly to Neon pruebas after authorization.
-- Historical percentages are retained. Unknown historical distance/calibration stays NULL.
BEGIN;
ALTER TABLE lecturas ADD COLUMN distancia_cm DOUBLE PRECISION;
ALTER TABLE lecturas ADD COLUMN nivel_calibracion TEXT;
ALTER TABLE lecturas ADD COLUMN temperatura_estado TEXT;
ALTER TABLE lecturas ADD COLUMN temperatura_observada DOUBLE PRECISION;
ALTER TABLE lecturas ADD CONSTRAINT lecturas_distancia_cm_rango
  CHECK (distancia_cm IS NULL OR (distancia_cm >= 2 AND distancia_cm <= 400));
ALTER TABLE lecturas ADD CONSTRAINT lecturas_nivel_calibracion_valida
  CHECK (nivel_calibracion IS NULL OR nivel_calibracion = 'provisional-7.8-2.0');
ALTER TABLE lecturas ADD CONSTRAINT lecturas_temperatura_estado_valido
  CHECK (temperatura_estado IS NULL OR temperatura_estado IN ('valida','sospechosa','invalida'));
ALTER TABLE lecturas ADD CONSTRAINT lecturas_temperatura_observada_rango
  CHECK (temperatura_observada IS NULL OR (temperatura_observada >= -55 AND temperatura_observada <= 125));
INSERT INTO aquamonitor_migraciones(version) VALUES(3);
COMMIT;
