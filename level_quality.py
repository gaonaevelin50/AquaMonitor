"""Validate provenance without recalculating or replacing the received percentage."""
import math
EMPTY_CM = 7.8
FULL_CM = 2.0
CALIBRATION_ID = "provisional-7.8-2.0"
ROUNDING_TOLERANCE_CM = 0.0099  # JSON: distance 0.01 cm and percentage 0.1 %.

def level_status(percentage, distance, calibration):
    if type(distance) not in (int,float) or not 2 <= distance <= 400 or not math.isfinite(distance):
        return "sin_distancia_valida"
    if calibration != CALIBRATION_ID:
        return "calibracion_no_identificada"
    if type(percentage) not in (int,float) or not 0 <= percentage <= 100 or not math.isfinite(percentage):
        return "porcentaje_no_valido"
    # Inverse check only. Never generate a new percentage in the API.
    if percentage == 0:
        compatible = distance >= EMPTY_CM-ROUNDING_TOLERANCE_CM
    elif percentage == 100:
        compatible = distance <= FULL_CM+ROUNDING_TOLERANCE_CM
    else:
        expected_distance = EMPTY_CM-(percentage/100.0)*(EMPTY_CM-FULL_CM)
        compatible = abs(distance-expected_distance) <= ROUNDING_TOLERANCE_CM
    return "valida" if compatible else "calibracion_incompatible"
