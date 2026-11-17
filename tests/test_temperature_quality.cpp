#include "../esp32/aquamonitor_esp32/temperature_quality.h"
#include <cassert>
#include <cstdio>
using namespace AquaMonitorTemperatura;
int main(){
 assert(clasificar(30.1f)==Estado::Valida);
 assert(clasificar(0)==Estado::Valida);assert(clasificar(50)==Estado::Valida);
 assert(clasificar(99.7f)==Estado::Sospechosa);assert(clasificar(-0.1f)==Estado::Sospechosa);
 assert(clasificar(125)==Estado::Sospechosa);
 assert(clasificar(85)==Estado::Invalida);assert(clasificar(-127)==Estado::Invalida);
 assert(clasificar(126)==Estado::Invalida);assert(clasificar(NAN)==Estado::Invalida);assert(clasificar(INFINITY)==Estado::Invalida);
 std::puts("PASS temperature digital validity versus aquarium plausibility; no fabricated replacements");
}
