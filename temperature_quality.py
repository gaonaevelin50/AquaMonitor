"""Configurable aquarium plausibility policy, not a DS18B20 calibration."""
import math
MIN_PLAUSIBLE_C = 0.0
MAX_PLAUSIBLE_C = 50.0

def classify_temperature(value):
    if type(value) not in (int,float) or not -55 <= value <= 125 or not math.isfinite(value) or value in (-127,85):
        return "invalida"
    return "valida" if MIN_PLAUSIBLE_C <= value <= MAX_PLAUSIBLE_C else "sospechosa"
