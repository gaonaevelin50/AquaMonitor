#include "../esp32/aquamonitor_esp32/water_level.h"
#include <cassert>
#include <initializer_list>
#include <cstdio>
using namespace AquaMonitorNivel;
int main() {
  // Synthetic fixture only: not the real aquarium calibration.
  const Calibracion c = {10.0f, 4.0f, true};
  float value;
  const float distance[] = {10, 7, 4, 3, 11};
  const float expected[] = {0, 50, 100, 100, 0};
  for (int i=0;i<5;i++) {
    assert(calcularPorcentaje(distance[i],c,value));
    assert(std::fabs(value-expected[i])<0.001f);
  }
  for (float bad : {-1.0f, 0.0f, 1.99f, 400.01f, NAN, INFINITY}) {
    assert(!calcularPorcentaje(bad,c,value)); assert(std::isnan(value));
  }
  const Calibracion badCalibration[]={{10,10,true},{4,10,true},{10,NAN,true},{10,4,false},{1,0,true}};
  for (const auto& bad : badCalibration) {
    assert(!calcularPorcentaje(7,bad,value)); assert(std::isnan(value));
  }
  assert(calibracionValida(CALIBRACION));
  assert(CALIBRACION_PROVISIONAL);
  const float legacyDistance[]={7.8f,6.35f,4.9f,3.45f,2.0f,8.11f,7.63f};
  const float legacyExpected[]={0.0f,25.0f,50.0f,75.0f,100.0f,0.0f,2.931034f};
  for (int i=0;i<7;i++) {
    assert(calcularPorcentaje(legacyDistance[i],CALIBRACION,value));
    assert(std::fabs(value-legacyExpected[i])<0.001f);
  }
  assert(!calcularPorcentaje(1.9f,CALIBRACION,value) && std::isnan(value));
  float noisy[]={8.0f,8.1f,200.0f,7.9f,8.05f};
  assert(mediana(noisy,5,value) && std::fabs(value-8.05f)<0.001f);
  float invalid[]={NAN,-1,0,8.0f,8.1f};
  assert(!mediana(invalid,5,value) && std::isnan(value));
  float mixed[]={8.0f,NAN,8.1f,8.2f,500};
  assert(mediana(mixed,5,value) && std::fabs(value-8.1f)<0.001f);
  assert(!mediana(nullptr,5,value));
  std::puts("PASS water-level formula, clamps, invalid echoes, calibration guards and median");
}
