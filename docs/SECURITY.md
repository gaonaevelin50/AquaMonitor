# Seguridad y propiedad

## Identidad y credenciales

El dispositivo crea dos secretos independientes de 256 bits usando `esp_fill_random` con radio habilitada. `ac_` identifica la credencial de configuración y `am_` la de medición. Neon guarda SHA-256 de los tokens completos, no sus valores. La MAC es metadato: dos inscripciones con la misma MAC no comparten identidad, propiedad ni datos.

La inscripción pública crea solo identidades nuevas sin acceso a cuentas. Está limitada por IP. Su UUID de inscripción y credencial de configuración hacen idempotentes los reintentos. No demuestra autenticidad de fabricante: AquaMonitor admite equipos configurados por sus usuarios.

El firmware guarda un único documento en NVS y comprueba su persistencia antes de enviar secretos al servidor. La renovación mantiene una credencial pendiente persistida y una generación UUID para recuperar respuestas perdidas. El registro y la renovación se repiten sin crear identidades o claves adicionales.

NVS no está cifrada automáticamente. Quien extraiga físicamente sus secretos puede suplantar ese equipo hasta que se bloquee. Cifrado de flash/NVS y Secure Boot requieren una etapa de aprovisionamiento aparte.

## Código temporal

12 caracteres Base32 (60 bits), 10 minutos, un solo uso. El servidor lo deriva con HMAC de una solicitud UUID y un secreto independiente; almacena otro HMAC para buscarlo. El ESP32 solo lo solicita durante configuración física inicial o al pulsar BOOT. No lo pongas en URL, logs de servidor ni enlaces públicos. El Monitor Serial lo muestra porque es el comprobante temporal solicitado por el usuario.

El backend no puede observar físicamente BOOT: confía en que el firmware solo solicite códigos bajo esas condiciones y en que la credencial privada de configuración permanezca secreta. Un código compartido o robado puede ser utilizado antes de caducar.

## Transacciones

Todos los cambios de propiedad, revocación, recuperación y recepción bloquean primero la fila del dispositivo. Después se comprueban credencial y asignación vigentes. La vinculación consume el código y crea la asignación dentro de la misma transacción. Un índice único parcial impide dos asignaciones abiertas.

Los límites de solicitudes se incrementan con `INSERT ... ON CONFLICT ... RETURNING` y se confirman antes de adquirir bloqueos. Persisten aunque falle posteriormente la operación. Son ventanas fijas; complementarlos con firewall de Vercel para ataques distribuidos. No son un sistema de protección DDoS completo.

## Historial

Cada lectura nueva referencia su asignación y su dispositivo mediante clave foránea compuesta. El servidor extrae ambos de la credencial autenticada. Campos `mac`, `device_id`, `owner_id`, `asignacion_id` en una recepción se rechazan.

Al liberar, la asignación se cierra y su historial queda para la cuenta anterior. El nuevo dueño abre otra asignación y recibe otra credencial de medición. No puede consultar datos del periodo anterior. Ni siquiera un mismo usuario que vuelva a vincular el equipo mezcla los periodos.

La migración 002 NO atribuye lecturas antiguas a la cuenta actual: no existe evidencia de propiedad histórica. Tampoco activa identidades para los dispositivos heredados. Esos registros y sus lecturas se conservan, pero no aparecen como nuevas asignaciones. Cualquier recuperación de ese historial requiere revisión y autorización posterior, sin atribución automática por MAC.

## Sesiones y navegador

Sesión aleatoria de 24 horas en cookie HttpOnly, SameSite=Strict y Secure en Vercel. El servidor guarda solo su hash. Logout revoca la sesión en la base. Las escrituras autenticadas requieren un token CSRF derivado de la sesión; el frontend lo mantiene solo en memoria. También se comprueba Origin y se rechazan solicitudes cross-site.

Las operaciones sensibles requieren la contraseña de la cuenta y tienen límites propios. Los secretos del equipo nunca son devueltos por endpoints de usuarios. El frontend usa `textContent` para entradas del usuario, y las respuestas API no se almacenan en caché.

No se imprime el contenido de excepciones de base de datos: puede incluir credenciales o detalles de conexión.

## Recuperación y bloqueo

Revocar no libera propiedad. Recuperar abre una autorización de 10 minutos que consume el canal del ESP32 al registrar una generación nueva. Una respuesta perdida se resuelve repitiendo esa misma generación. Una generación revocada nunca puede volver a activarse.

Bloquear revoca ambas credenciales y mantiene propiedad e historial. No existe un endpoint público de desbloqueo. Un reprovisionamiento físico crea otra identidad sin heredar registros anteriores; recuperar o transferir datos históricos exige un procedimiento separado revisado por el propietario.

## TLS y disponibilidad

Cloud: HTTPS, CA raíz y reloj NTP en ESP32; nunca `setInsecure()`. PostgreSQL: `verify-full` y CA de confianza en producción. La API rechaza la clave global antigua sin excepciones, también para equipos heredados.

Los reintentos de red usan espera progresiva. No hay cola persistente de mediciones: durante un corte pueden perderse muestras. Esta etapa no garantiza entrega exacta una vez ni recuperación de lecturas offline.

Planificar mantenimiento explícito de sesiones vencidas, contadores antiguos y solicitudes cerradas. No hay tareas automáticas de borrado ni cambios de esquema al arrancar.

## Proxy y Bluetooth

En Vercel se confía solo en el esquema HTTPS y la IP proporcionados por su proxy administrado. Fuera de Vercel se ignora `X-Forwarded-For`. Si se aloja detrás de otro proxy, revisar expresamente esta configuración antes de publicar.

BLE conserva el comportamiento local previo y no autentica al propietario de la cuenta. No entrega historial de Neon ni credenciales, pero una persona próxima puede leer las mediciones BLE anunciadas por el equipo. Añadir emparejamiento BLE autenticado requiere una etapa adicional.
