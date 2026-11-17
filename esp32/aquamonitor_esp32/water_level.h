#pragma once
#include <cmath>
#include <stddef.h>

namespace AquaMonitorNivel {
constexpr float DISTANCIA_MINIMA_CM = 2.0f;
constexpr float DISTANCIA_MAXIMA_CM = 400.0f;

struct Calibracion {
  float distanciaVacia;
  float distanciaLlena;
  bool habilitada;
};

// Owner-authorized legacy calibration, enabled only as a PROVISIONAL reference.
// These are not new physical measurements; physical verification remains pending.
constexpr bool CALIBRACION_PROVISIONAL = true;
const Calibracion CALIBRACION = {7.8f, 2.0f, true};

inline bool distanciaValida(float cm) {
  return std::isfinite(cm) && cm >= DISTANCIA_MINIMA_CM && cm <= DISTANCIA_MAXIMA_CM;
}

inline bool calibracionValida(const Calibracion& c) {
  return c.habilitada && distanciaValida(c.distanciaVacia) && distanciaValida(c.distanciaLlena)
      && c.distanciaVacia > c.distanciaLlena;
}

inline bool calcularPorcentaje(float actual, const Calibracion& c, float& porcentaje) {
  porcentaje = NAN;  // Invalid never becomes a plausible zero/full measurement.
  if (!distanciaValida(actual) || !calibracionValida(c)) return false;
  porcentaje = (c.distanciaVacia - actual) / (c.distanciaVacia - c.distanciaLlena) * 100.0f;
  if (porcentaje < 0.0f) porcentaje = 0.0f;
  if (porcentaje > 100.0f) porcentaje = 100.0f;
  return true;
}

// Fixed stack storage: no new heap use during HTTPS. At least three valid echoes.
inline bool mediana(const float* entradas, size_t cantidad, float& distancia) {
  distancia = NAN;
  if (!entradas || cantidad > 5) return false;
  float validas[5];
  size_t n = 0;
  for (size_t i = 0; i < cantidad; ++i) {
    if (!distanciaValida(entradas[i])) continue;
    float x = entradas[i];
    size_t j = n;
    while (j > 0 && validas[j-1] > x) { validas[j] = validas[j-1]; --j; }
    validas[j] = x;
    ++n;
  }
  if (n < 3) return false;
  distancia = n % 2 ? validas[n/2] : (validas[n/2-1] + validas[n/2]) / 2.0f;
  return true;
}
}
