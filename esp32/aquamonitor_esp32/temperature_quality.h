#pragma once
#include <cmath>
namespace AquaMonitorTemperatura {
// Aquarium plausibility policy only; the DS18B20 calibration is unchanged.
constexpr float MIN_PLAUSIBLE_C = 0.0f;
constexpr float MAX_PLAUSIBLE_C = 50.0f;
enum class Estado { Valida, Sospechosa, Invalida };
inline Estado clasificar(float value) {
  if (!std::isfinite(value) || value < -55.0f || value > 125.0f || value == -127.0f || value == 85.0f) return Estado::Invalida;
  return value >= MIN_PLAUSIBLE_C && value <= MAX_PLAUSIBLE_C ? Estado::Valida : Estado::Sospechosa;
}
inline const char* texto(Estado estado) {
  return estado == Estado::Valida ? "valida" : estado == Estado::Sospechosa ? "sospechosa" : "invalida";
}
}
