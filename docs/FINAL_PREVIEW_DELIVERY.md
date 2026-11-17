# Entrega web final AquaMonitor — Preview

URL: https://aquamonitor-5ym9reup8-rota-smart1.vercel.app
Despliegue: dpl_Egh2mZYRkh6DyTHyNo2fehyo4sXN; estado READY; entorno Preview, no Production.

Se publicaron backend, temperature_quality.py y frontend desde una copia limpia.
No se incluyeron .env, secrets.h, firmware, migraciones ni artefactos de pruebas.
Las seis variables Preview se reutilizaron sin cambios y Production conserva
su despliegue, variables y protección. Se habilitó únicamente la excepción
pública del nuevo Preview tras autorización expresa del propietario.

## Integridad

Neon Pruebas continúa en esquema 002, sin aplicar la 003.
Se compararon huellas por registro antes y después: cero filas previas borradas
o modificadas en usuarios, dispositivos (salvo campos de recepción volátiles que
se excluyeron del hash), credenciales, asignaciones, sesiones, solicitudes y lecturas.
Se conservaron 7 usuarios, 6 dispositivos, 15 credenciales, 6 asignaciones,
22 sesiones, 7 solicitudes y las 976 lecturas previas. Las pruebas solo escribieron
en bases locales nuevas, nunca en Neon. No se realizaron commits ni push.

## Pruebas

Antes: 35 pruebas Python, tres grupos C++ y dos recorridos de navegador locales.
Después: 35 pruebas Python, tres grupos C++, recorrido completo de navegador local,
y comprobaciones sobre el JavaScript publicado con API interceptada. Todo aprobado.
Las rutas públicas HTML/JS/CSS devuelven 200 y coinciden byte a byte con la copia
preparada. Las rutas privadas devuelven 401 JSON sin sesión; no hubo redirección
final al acceso de Vercel tras habilitar la excepción autorizada.

Se comprobó el renderizado de la última muestra existente usando una copia de
solo lectura y API interceptada: se informa antigüedad y hora de recepción,
sin presentar el porcentaje antiguo como actual. No se abrió sesión real en
Preview porque ello crearía una nueva sesión en Neon, prohibido para esta entrega.
El propietario debe entrar en el enlace nuevo con su cuenta existente; no hace
falta crear ni reiniciar la cuenta. La cookie de otro dominio no se transfiere.

Incidencias resueltas: bloqueo inicial de Vercel y codificación de un archivo
auxiliar de pruebas. Ambas se corrigieron y verificaron; no fueron cambios de datos.

## Dispositivo y límites de esta entrega

El ESP32 conocido conserva vínculo y credenciales activas. Última recepción
observada: 2026-11-17 01:56:48, America/Bogota (UTC-5). No había datos recientes en la
verificación. No se afirma recepción física en vivo: no se accedió, reinició ni
cargó el dispositivo durante esta entrega.

La calibración 7,8/2,0 y los casos 0/50/100 se verificaron en pruebas del firmware
preparado. La web no recalcula el porcentaje recibido. El ESP32 aún conserva su
firmware y URL anteriores; por tanto esta publicación web no cambia por sí sola
el cálculo que ejecuta la placa. Una futura actualización necesita autorización
separada para configurar el destino correcto, validar TLS, recompilar y cargar.

Destino previsto para esa futura configuración (no aplicado):
https://aquamonitor-5ym9reup8-rota-smart1.vercel.app/api/lecturas

No se necesita la 003 para guardar las mediciones principales. Sin ella, distancia
y diagnósticos opcionales no persistidos se indican como no disponibles, sin inventar
valores. El 99,7 se clasifica como sospechoso, no como temperatura actual válida.

Informe verificable local: `.test-runtime/final-release-report.json`.
