# Calibración provisional del nivel de AquaMonitor

## Referencia habilitada para presentación

Por instrucción expresa del propietario se recuperaron los valores de la versión
anterior, sin presentarlos como nuevas mediciones físicas:

```cpp
const Calibracion CALIBRACION = {7.8f, 2.0f, true};
constexpr bool CALIBRACION_PROVISIONAL = true;
```

En `water_level.h` el tercer campo se llama `habilitada`: true permite calcular
el porcentaje, pero NO significa que las distancias hayan sido verificadas en
el montaje actual. Serial identifica esta calibración como PROVISIONAL.
No se utilizó 7,29 cm ni se dedujo el máximo a partir de la lectura de 7,70 cm.

## Fórmula y validación

`porcentaje = (distanciaVacia - distanciaActual) / (distanciaVacia - distanciaLlena) * 100`

El resultado se limita a 0–100 %. Se exigen distancias finitas entre 2 y 400 cm,
calibración habilitada y vacío mayor que lleno. No hay división entre cero.
Un eco inválido se descarta: nunca se convierte automáticamente en 0 o 100 %.
Se conservan cinco muestras, mediana con al menos tres ecos válidos y separación
acústica de 60 ms. La implementación usa memoria fija de pila y centímetros.

Con la referencia provisional: 7,8 cm produce 0 %; 2,0 cm produce 100 %.
El punto matemático de 50 % es 4,9 cm: es un caso de prueba, no una medida
física nueva. Una lectura de 7,70 cm produce aproximadamente 1,7 %, no 50 %.
Si esa lectura corresponde a media pecera en el montaje real, debe comprobarse
el eco y sustituirse la referencia provisional con dos distancias reales.

## Flujo de datos conservado

El firmware envía `nivel_agua` como porcentaje cuando el eco es válido.
Si no lo es, omite únicamente el nivel; temperatura y turbidez continúan.
El backend almacena el porcentaje sin recalcularlo y el historial lo muestra
con el símbolo %. El dashboard usa el mismo número. No se modificaron esos
componentes para esta calibración ni se reescribieron registros históricos.

La inconsistencia anterior se explica por la referencia 30/5 encontrada en el
código: `(30-7.70)/(30-5)*100 = 89.2`. No era otra fórmula del dashboard.

## Verificación física pendiente

Mantener el sensor fijo, vertical y con ambos transductores libres de la tapa.
Medir con regla desde la cara de los transductores y anotar varias lecturas de
vacío y máximo permitido. No acercar el agua a la zona inferior a 2 cm del sensor.
Comprobar después la mitad real de la altura útil. Si la distancia apenas cambia
al añadir agua, investigar ecos de tapa y paredes antes de ajustar valores.
Estos pasos no impiden usar la referencia provisional autorizada para la presentación.

## Pruebas y compilación

- Pruebas C++ sobre la implementación real: 0/50/100 %, límites, rango,
  ecos inválidos, NaN/infinito, calibración degenerada/deshabilitada y mediana.
- Casos específicos de la referencia 7,8/2,0 y su condición provisional.
- Tres pruebas de backend/historial/dashboard con base simulada, sin Neon.
- Comprobación estática de pines, temperatura, turbidez y TLS aprobada.
- ESP32 Dev Module, Huge APP: programa 1 456 480 bytes (46 %),
  variables globales 60 420 bytes (18 %).

La conexión, secretos, TLS y autenticación no cambiaron. No se cargó firmware.
El binario está en `.test-runtime/firmware-level-build`; sus metadatos están en
`.test-runtime/firmware-level-ready.json`.


## Trazabilidad y frescura preparadas posteriormente

La auditoría completa y el siguiente paquete controlado están en
`WATER_LEVEL_TRACE.md`: agregan distancia y referencia al JSON, una migración
003 pendiente para almacenarlas y correcciones de caducidad/representación.
La fórmula y la referencia provisional 7,8/2,0 permanecen. El firmware
no se ha cargado, no se desplegó esta revisión ni se ejecutó la migración.


## Actualización local posterior: calidad DS18B20 y migración opcional

El estado vigente está en `CONTROLLED_SENSOR_UPDATE.md`. La 003 ya no bloquea
las mediciones principales: es opcional para persistir distancia y diagnósticos.
La compatibilidad con 002 y la conservación de históricos fueron probadas en
PostgreSQL local. El firmware y la web siguen sin cargarse/desplegarse.
