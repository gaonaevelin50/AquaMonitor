# Corrección local preparada: nivel, DS18B20 y frescura

## Estado

No se cargó firmware ni se desplegó esta revisión. No se conectaron las pruebas
a Neon ni se ejecutaron allí migraciones. El programa compilado ocupa 1 457 908
bytes (46 %) y 60 436 bytes globales (18 %), ESP32 Dev Module / Huge APP.
Metadatos y huellas: `.test-runtime/sensor-correction-ready.json`.

## Nivel

Se conserva la referencia provisional original 7,8 cm vacío / 2,0 cm lleno y
`((7.8-distancia)/(7.8-2.0))*100`, limitado a 0–100 solo con eco válido.
La sonda de turbidez no se utiliza como referencia de llenado máximo.
Cinco muestras, tres ecos válidos mínimos, mediana y rango 2–400 cm permanecen.
La lógica de turbidez, sus 20 muestras, pines y calibraciones no cambiaron.

La placa todavía ejecuta la versión anterior hasta autorizar una carga física.
Modificar la web no cambia la fórmula que ejecuta el ESP32.

## Calidad DS18B20

`temperature_quality.h` y `temperature_quality.py` separan:
- válida: lectura digital admisible y dentro de la política de plausibilidad;
- sospechosa: trama admisible, pero fuera de la política de la pecera;
- inválida: lectura no finita, rango técnico inválido, sonda/dirección/CRC/conversión
  fallidos, desconexión o valor de arranque 85 °C.

La política predeterminada es 0–50 °C, configurable y explícita. No cambia la
calibración del DS18B20 ni sustituye valores medidos. Los límites técnicos usados
son -55 a 125 °C; cumplirlos no demuestra plausibilidad física en esta pecera.

El firmware solicita conversión bloqueante por dirección DS18B20 y utiliza la
verificación de scratchpad/CRC de DallasTemperature. Una lectura de 99,7 °C se
imprime como SOSPECHOSA y no ocupa el campo de temperatura válida ni el paquete
BLE de temperatura; se conserva por separado como diagnóstico cuando es posible.
Nunca se sustituye por cero ni por una temperatura anterior.

El backend también protege frente al firmware anterior: si recibe 99,7 como
`temperatura`, la clasifica y la separa de la temperatura utilizable. Las demás
mediciones válidas continúan. Si no hay ninguna medición utilizable, devuelve un
error explícito en vez de guardar una lectura vacía. El dashboard oculta el valor
numérico actual sospechoso y muestra un aviso; también protege el paquete BLE
anterior. El historial existente conserva su valor bruto; la etiqueta de calidad
se calcula al leer, sin actualizar filas antiguas.

Esto contiene el dato anormal, pero no demuestra su causa física. La validación
final requiere contrastar la sonda con un termómetro y observar la versión nueva
tras una carga autorizada.

## Antigüedad

API y dashboard mantienen el límite de 30 segundos por medición, además del
estado del dispositivo. Un temporizador independiente retira valores vencidos
incluso si una petición queda pendiente; también cubre notificaciones BLE.
La última recepción queda visible con fecha y hora y el aviso «sin lectura actual».
Cambiar de dispositivo o cerrar sesión limpia la referencia anterior.

## Migración 003: opcional, no requisito de funcionamiento

Se revisó para añadir únicamente columnas nullable de distancia, referencia y
calidad/valor observado de temperatura. No borra ni recalcula históricos.
Es necesaria solo para persistir estos diagnósticos y mostrarlos posteriormente
por WiFi. No es necesaria para corregir el porcentaje, rechazar temperaturas
sospechosas o controlar antigüedad.

Con esquema 002 el backend guarda el núcleo de mediciones utilizables y responde
`trazabilidad_guardada=false`. El firmware avisa que los diagnósticos no se
persistieron. No hay error 503 ni bloqueo de las lecturas por falta de la 003.
Sin esa migración la distancia/diagnóstico no se inventan para el dashboard:
se informa que no están disponibles. El diagnóstico completo sigue en Serial.

La migración se ejecutó y probó únicamente en una base local nueva desechable,
comprobando que una fila histórica sintética quedaba idéntica. Antes de aplicarla
en pruebas hay que autorizarlo y revisar versiones/columnas; no repetir una 003
que ya se hubiese aplicado manualmente con otro contenido.

## Pruebas

- 35 pruebas Python finales, incluidas concurrencia, aislamiento, CSRF, cookies,
  vinculación, revocación, recuperación, historial y esquemas 002/003 locales.
- Tres grupos C++: nivel original, política térmica y función real de lectura
  DS18B20 con respuestas simuladas de dirección/CRC/conversión.
- Dos recorridos Chrome: visual/frescura/calidad con API simulada y recorrido
  completo de usuario/dispositivo sobre la base local desechable.
- Compilación real ESP32 correcta. Hardware nuevo todavía no probado ni cargado.

## Actualización controlada pendiente

1. Autorizar publicación exclusivamente Preview del backend/frontend. Incluir
   `temperature_quality.py` además de app.py, aquamonitor_api.py, requirements,
   vercel.json, .python-version y public/. Excluir .env, secrets.h, firmware y
   archivos privados. Mantener las seis variables Preview y Neon pruebas.
2. Verificar registro/login, recepción compatible y antigüedad en Preview.
3. Decidir si se necesita persistir diagnóstico. Si se aprueba, aplicar la 003
   solo a pruebas tras comprobar host, versión y columnas. Puede omitirse.
4. Autorizar después la carga del binario verificado en el ESP32: Huge APP,
   EraseFlash=none, sin borrar NVS ni cambiar credenciales.
5. Contrastar Serial/API/dashboard/historial con la misma muestra y confirmar
   plausibilidad DS18B20 con referencia física. No recalcular porcentajes en web.

No se necesitan cambios de WiFi, TLS, autenticación, sesiones o vinculación.


## Comprobación obligatoria del destino antes de cargar

`secrets.h` no se modificó: el binario conserva la URL del Preview anterior.
Publicar un nuevo Preview NO actualiza esa URL del ESP32. Antes de autorizar la
carga debe confirmarse que el destino del dispositivo contiene el backend nuevo:
si el nuevo despliegue tiene otro enlace, autorizar el ajuste de SERVER_URL (o de
un alias Preview estable), validar CA/dominio y recompilar con ese destino.
No cambiar tokens, WiFi ni usar excepciones TLS. Cargar este binario contra el
backend anterior podría rechazar los nuevos campos JSON: no se considera listo
para activar físicamente hasta completar esa comprobación.

## Archivos de esta etapa

- `esp32/aquamonitor_esp32/aquamonitor_esp32.ino`
- `esp32/aquamonitor_esp32/secure_network.h` (solo cuerpo/resultado de mediciones)
- `esp32/aquamonitor_esp32/temperature_quality.h` (nuevo)
- `temperature_quality.py` (nuevo)
- `aquamonitor_api.py`
- `public/script.js`
- `migrations/003_level_trace.sql` (revisada, opcional, no aplicada en Neon)
- `tools/check_firmware.ps1`
- `tests/test_level_trace.py`
- `tests/test_temperature_quality.cpp` y `tests/test_temperature_quality.py`
- `tests/test_optional_trace_integration.py`
- `tests/level_dashboard_e2e.cjs` y `tests/browser_e2e.cjs`
- Esta guía y notas de estado en WATER_LEVEL_TRACE.md / WATER_LEVEL_CALIBRATION.md.

`water_level.h` conserva sin cambios la referencia provisional original.
Los cambios visuales HTML/CSS preparados en la etapa anterior siguen formando
parte del paquete para Preview. El servidor local de uso normal no se reinició
en esta etapa: la prueba completa utilizó el servidor separado 5059, ya detenido.
Para activar el backend en localhost también habrá que reiniciar su proceso.
