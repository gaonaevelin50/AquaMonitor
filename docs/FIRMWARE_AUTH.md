# Firmware y autenticación del Preview

El mensaje «ERROR 401: la API KEY no coincide con Vercel» no existe en el firmware fuente actual. Indica una versión anterior u otro sketch ejecutándose en la tarjeta; no se ha leído ni sustituido su firmware para confirmar el binario físico.

## Versión preparada

Abre `esp32/aquamonitor_esp32/aquamonitor_esp32.ino` y conserva en esa misma carpeta `secure_network.h` y tu `secrets.h` privado. El inicio muestra `AquaMonitor firmware device-bearer-v2.1`, para distinguirlo de una versión antigua.

La clave global `AQUAMONITOR_API_KEY` ya no se utiliza. Cambiar esa clave no resuelve la incompatibilidad. No se han añadido excepciones al backend ni desactivado autenticación.

## Protocolo implementado

| Etapa | Ruta | Autenticación |
| --- | --- | --- |
| Inscripción idempotente | POST /api/equipos/registro | Bearer ac_ con 64 dígitos hexadecimales |
| Código temporal | POST /api/equipos/vinculacion | Credencial de configuración ac_ |
| Estado | GET /api/equipos/estado | Credencial de configuración ac_ |
| Vinculación desde la cuenta | POST /api/dispositivos/vincular | Sesión del usuario y CSRF |
| Mediciones | POST /api/lecturas | Credencial individual am_ |
| Recuperación autorizada | POST /api/equipos/credenciales/medicion | ac_ y autorización vigente del propietario |

El ESP32 genera sus credenciales y UUID, los guarda en NVS y nunca muestra tokens. Solo muestra el código temporal de 12 caracteres Base32, de un uso y hasta 10 minutos. La MAC se envía como metadato únicamente al registrar; no se utiliza para autenticar ni se incluye en las mediciones.

## Configuración privada pendiente

En la inspección de esta etapa, la URL, CA y contraseña del portal del `secrets.h` local estaban vacías. No se ha modificado ese archivo.

- `AQUAMONITOR_SERVER_URL`: endpoint público `https://aquamonitor-gd8ilkz0d-rota-smart1.vercel.app/api/lecturas`.
- `AQUAMONITOR_ROOT_CA`: certificado raíz PEM real que valide ese dominio. No inventarlo ni usar el certificado de otro servicio.
- `AQUAMONITOR_WIFI_PORTAL_PASSWORD`: contraseña privada de 8 a 63 caracteres.

La CA se valida con `setCACert(ROOT_CA_CERT)` y el reloj se sincroniza por NTP. No se usa `setInsecure()`. Si faltan datos, se indican sus nombres sin mostrar valores privados.

## Uso después de autorizar la carga física

1. Compilar el sketch correcto con ESP32 3.3.11, WiFiManager 2.0.17, ArduinoJson 7.4.3, OneWire y DallasTemperature. Partición Huge APP para WiFi y BLE.
2. Tras cargarlo en una etapa autorizada, confirmar el identificador `device-bearer-v2.1` en Serial a 115200.
3. Configurar WiFi de 2.4 GHz. El portal protegido requiere usuario `aquamonitor` y tu contraseña del portal.
4. Pulsar brevemente BOOT si hace falta activar vinculación; consultar el código por Serial o `/vinculacion` en el portal local.
5. En el Preview, abrir Dispositivos → Añadir mediante código. Una vez vinculado, Serial indica que los envíos individuales están habilitados.
6. Comprobar las mediciones e historial. Revocar detiene la credencial de medición; recuperar requiere autorización desde la cuenta.

BOOT durante 3 segundos restablece solo WiFi. No libera propiedad ni borra automáticamente la identidad ante un 401.

## Validación de esta etapa

- Compilación correcta: 1 933 423 bytes de programa (61 %) y 65 244 bytes globales (19 %).
- 18 comprobaciones HTTPS del protocolo contra Preview aprobadas con una cuenta y un dispositivo sintéticos: rechazo de clave global, registro, código, vinculación, estado, recepción, historial y revocación.
- Comparación exacta de funciones de sensores y adquisición; pines y calibraciones conservados. `secrets.h` sin cambios.
- La compilación usa una copia de la plantilla pública vacía, no secretos reales. No se ha cargado firmware al ESP32.
- La prueba de protocolo es un cliente simulado; la conexión, NVS, portal y código en la tarjeta real quedan pendientes de configurar y cargar el firmware con autorización.


## Revisión TLS y memoria (2026-11-16, sin nueva carga física)

La CA privada se comprobó sin modificarla ni publicar su PEM. Es GTS Root R1,
con restricción CA y vigencia 2016-06-22 a 2036-06-22. Vercel presentó
`*.vercel.app -> WR1 -> GTS Root R1 (firma cruzada de GlobalSign)`.
La validación TLS 1.2 usando exclusivamente la raíz configurada y el nombre
real del Preview fue correcta. El ancla elegida coincide por SHA-256.
Los sujetos, emisores, fechas y huellas completas se conservan localmente en
`.test-runtime/tls-chain-diagnosis.json`; no contiene PEM ni credenciales.

El reloj físico observado fue 1794886079: 2026-11-17 03:27:59 UTC
(2026-11-16 22:27:59 en Colombia). Todos los certificados estaban vigentes.
Esto no revela la causa interna exacta de -9984 en mbedTLS: el firmware anterior
no conservó los indicadores específicos de verificación antes de liberar TLS.
No se justifica reemplazar la CA ni desactivar la validación.

Los errores -10368 y -16256 demuestran fallos de reserva de memoria.
Se encontraron dos contextos TLS vivos simultáneamente en la ruta de diagnóstico:
http.end() no destruía el objeto cliente antes de crear el segundo cliente.
Ahora ambos objetos HTTP/TLS salen de ámbito antes de la prueba independiente.

Se reemplazó Bluedroid por **NimBLE-Arduino 2.5.2** para conservar Bluetooth con
menor presión de RAM. Instalar esa dependencia para compilar; Huge APP permanece.
Se conservan nombre, UUID, lectura/notificaciones y paquete de ocho bytes.
La reducción real de heap y la conexión BLE deben medirse en el dispositivo;
el tamaño del binario no demuestra por sí mismo la RAM libre durante TLS.

La respuesta JSON se procesa directamente desde el stream HTTP/1.0 para evitar
una copia String completa y evitar chunked en ese stream. Cada petición sigue
validando CA y dominio, sin redirecciones. La CA se referencia con setCACert;
la librería la analiza al conectar, no al asignar ese puntero.

Los nuevos mensajes muestran RAM interna libre, mayor bloque y mínimo histórico
antes/después de BLE, WiFi y HTTPS. Se exige confirmación SNTP real y se imprime
fecha UTC/Unix. No se imprimen SSID, contraseña, tokens, cabeceras ni certificados.
Las mediciones nuevas y la confirmación de la solución TLS requieren una carga
física posterior expresamente autorizada; no se simulan resultados.


## Flujo WiFi listo para la siguiente carga autorizada

- Portal local protegido por contraseña WiFi y autenticación HTTP del portal;
  credenciales WiFi e identidad individual persistidas en NVS, sin exportarlas al navegador.
  No se ha habilitado cifrado de flash/NVS mediante eFuses: persistencia no implica
  protección frente a extracción física de la memoria.
- Reconexión STA automática y portal de configuración tras una caída prolongada;
  asociación WiFi, dirección IP, DNS y acceso HTTPS se distinguen en Serial.
- El registro inicial interrumpido puede completarse con la identidad ya guardada.
  Tras el primer registro confirmado se activa la solicitud del código al backend;
  nunca se inventa localmente. Se imprimen vencimiento UTC y segundos restantes.
- Abrir el Preview, iniciar sesión, Dispositivos -> añadir mediante código y nombre.
  Las credenciales individuales se generan con el generador criptográfico del ESP32
  y se guardan antes del registro, según el protocolo ya existente; el backend
  conserva sus hashes y confirma su habilitación después de vincular la cuenta.
- Los envíos utilizan reintentos con espera creciente. Durante un corte se reanudan
  con las lecturas actuales; esta versión no incorpora una cola persistente de
  todas las muestras tomadas sin conexión.
- Serial anuncia registro, vinculación y autenticación según respuestas reales.
  Solo anuncia una medición guardada cuando el backend devuelve HTTP 200.

Compilación final: 1 456 276 bytes de programa (46 %) y 60 420 bytes globales (18 %),
con Huge APP. Metadatos y huellas locales en `.test-runtime/firmware-ready.json`.
Nuevas mediciones de heap en ejecución pendientes de carga física autorizada.

`tools/check_wifi_flow.py` comprobó el flujo con TLS 1.2, la misma CA del firmware
 y HTTP/1.0: registro, presencia del registro en Neon pruebas, código backend vigente,
cuenta sintética, inicio de sesión, vinculación con nombre, estado habilitado,
dos envíos, valores del dashboard e historial de seis filas de sensores.
El código consumido fue rechazado al intentar reutilizarlo. Solo se crearon datos QA
nuevos en pruebas; no se eliminaron registros anteriores. Resultado local:
`.test-runtime/wifi-flow-result.json`. Esta prueba simula el cliente: no demuestra
que la nueva pila BLE/TLS ya haya funcionado en el ESP32 físico.


## Calibración provisional autorizada para presentación

La corrección de nivel más reciente habilita como referencia provisional los
valores anteriores de 7,8 cm (vacío) y 2,0 cm (lleno). La verificación física
sigue pendiente. Se conservan fórmula, filtros y protecciones; no se cargó
firmware. Consultar `WATER_LEVEL_CALIBRATION.md` para el estado vigente.
