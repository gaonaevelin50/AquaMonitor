# Preparación de despliegue: Vercel + Neon + ESP32

Este documento prepara el trabajo posterior. Ningún comando de producción ha sido ejecutado durante la implementación.

## 1. Revisar la versión antes de publicar

Los archivos tienen cambios locales sin commit. No se han hecho commits ni push. Conserva las copias de `.audit-backups/` para comparación local; no las subas.

Revisa el diff, las pruebas y los nuevos archivos antes de autorizar una versión en Git. `.env`, `secrets.h`, bases, copias y artefactos de compilación están excluidos. `.vercelignore` protege también los despliegues desde CLI y `excludeFiles` reduce el paquete Python.

## 2. Preparar la base elegida

Usa una base separada para staging. No apuntes pruebas ni simuladores a producción.

La migración 001 se conserva. La 002 añade asignaciones, credenciales, códigos, eventos, sesiones, contadores y marcador de versión, sin borrar tablas ni lecturas. Quita la unicidad de MAC porque deja de ser identidad. No atribuye lecturas antiguas ni crea asignaciones para dispositivos heredados.

Antes de producción: revisar respaldo, permisos, disponibilidad y tratamiento de registros antiguos. El cambio invalida el protocolo de clave global y las sesiones antiguas. Requiere coordinar backend, frontend y reprovisionamiento del firmware. No ejecutar durante una transición sin plan.

Cuando exista autorización para el entorno correspondiente, aplicar los archivos mediante una herramienta SQL que use la conexión privada del entorno, en orden 001 (si es una base nueva) y 002. La 002 se ejecuta una sola vez; incluye su propia transacción. No copiar contraseñas a comandos, historial del terminal ni logs.

Confirmar columnas, relaciones, índices y `aquamonitor_migraciones.version=2`. Solo entonces habilitar `AQUAMONITOR_DB_SCHEMA_READY=true`. La aplicación nunca ejecuta SQL de migración automáticamente.

## 3. Variables del backend

| Variable | Configuración |
| --- | --- |
| `DATABASE_URL` | Conexión privada a la base correcta de Neon; se recomienda su endpoint pooled. |
| `POSTGRES_URL` | Alternativa, solo si no se usa `DATABASE_URL`. |
| `SECRET_KEY` | Secreto aleatorio independiente de al menos 32 caracteres; protege CSRF. No reutilizar la clave del portal ni de equipos. |
| `AQUAMONITOR_PAIRING_PEPPER` | Otro secreto aleatorio de al menos 32 caracteres; protege códigos. No igual a `SECRET_KEY`. |
| `AQUAMONITOR_DB_SCHEMA_READY` | `false` hasta verificar 001 y 002; `true` después. |
| `AQUAMONITOR_DB_SSLMODE` | `verify-full` en producción. El backend rechaza un modo inferior en Vercel. |
| `AQUAMONITOR_DB_SSLROOTCERT` | Ruta real a un paquete CA de confianza accesible al runtime. Validar la ruta en el entorno. |
| `VERCEL` | La proporciona Vercel; activa cookies Secure y restricciones de producción. |
| `PORT` | Opcional únicamente para ejecución local. |

`AQUAMONITOR_API_KEY` ya no se lee ni se acepta. No hay una clave nueva global que reemplazar.

Genera los secretos reales en un gestor seguro y configúralos en Vercel. No se han generado ni modificado secretos de producción. Rotar `SECRET_KEY` obliga al frontend a recuperar CSRF mediante `/api/me`; para invalidar sesiones hay que revocarlas en la tabla. Rotar el pepper invalida solicitudes de vinculación pendientes, pero no las credenciales de equipos ya vinculados.

El cliente de PostgreSQL usa `verify-full`; no basta con cambiar parámetros en la URL si el modo configurado es distinto. En Linux suele haber un paquete de CA del sistema; confirma su ruta efectiva y que valide Neon. Para un paquete propio, obtenerlo de una fuente oficial y mantenerlo actualizado. No desactivar TLS para resolver un error de certificados.

La excepción `sslmode=disable` se usa solo en el clúster local desechable de pruebas, ligado a loopback.

## 4. Configuración de Vercel

- Framework Flask; directorio raíz del repositorio.
- `app.py` exporta `app`; Python fijado en `.python-version` a 3.13.
- Instalar `requirements.txt`; no usar el `Procfile` antiguo ni iniciar `python app.py` como servidor persistente de producción.
- `public/index.html`, `public/styles.css` y `public/script.js` se sirven desde CDN en la raíz. Las rutas `/api/*` pertenecen a Flask.
- `vercel.json` configura cabeceras y exclusiones; no reescribe todas las peticiones a HTML.
- Asignar secretos independientes a Preview y Production; usar bases diferentes.
- Revisar Deployment Protection y firewall para permitir que el ESP32 acceda a su API sin una sesión de Vercel. No incluir una clave de bypass global en el firmware.
- Configurar la región de ejecución próxima a Neon según disponibilidad del plan.

No se ha ejecutado `vercel deploy` ni un build de Vercel. La compatibilidad está preparada por estructura y configuración; requiere verificación real del runtime, el paquete de CA y el dominio.

Fuentes oficiales: [Flask en Vercel](https://vercel.com/docs/frameworks/backend/flask), [runtime Python](https://vercel.com/docs/functions/runtimes/python), [TLS de Neon](https://neon.com/docs/connect/connect-securely).

## 5. Dominio y HTTPS del ESP32

1. Elegir el dominio real del despliegue autorizado; usar el dominio estable de producción o configurar uno propio en Vercel.
2. Esperar a que Vercel complete DNS y certificado HTTPS.
3. Comprobar la cadena de certificados de ese host real desde un cliente de confianza. Identificar la CA raíz y obtener su PEM de la autoridad oficial. No adivinar la CA por el nombre del proveedor.
4. Configurar localmente `AQUAMONITOR_SERVER_URL` con ese origen y `/api/lecturas`; sin redirecciones a otro host.
5. Poner el certificado raíz PEM en `AQUAMONITOR_ROOT_CA`, conservando las comillas y saltos `\n` del literal C++.
6. Configurar una contraseña única de portal de 8 a 63 caracteres. No reutilizar credenciales de cuenta ni claves del backend.
7. Compilar con ESP32 core 3.3.11, OneWire, DallasTemperature, WiFiManager 2.0.17 y ArduinoJson 7.4.3. WiFi+BLE requieren la partición Huge APP.
8. Cargar al hardware únicamente después de autorización adicional.
9. Permitir NTP y HTTPS en la red WiFi. Validar registro, código, vinculación y recepción real.

El firmware conserva `cliente.setCACert(ROOT_CA_CERT)` y no sigue redirecciones. Un cambio de dominio o CA puede exigir actualizar la configuración y volver a compilar. La renovación normal del certificado del servidor no exige cambios si continúa bajo una raíz confiable válida.

## 6. Verificaciones posteriores al despliegue autorizado

- `/`, CSS y JavaScript cargan; cabeceras de seguridad presentes también en CDN.
- Registro/login/logout y cookie Secure/HttpOnly; CSRF rechaza solicitudes sin token.
- Un ESP32 se registra y muestra código; una cuenta lo vincula.
- Otra cuenta no puede ver ni gestionar sus datos.
- Revocación detiene los envíos; recuperación utiliza una generación nueva.
- Transferencia conserva aislamiento del historial.
- Reinicio y pérdida de WiFi conservan identidad; no crean equipos duplicados.
- Pérdida de respuesta durante inscripción o renovación no bloquea el equipo.
- Supervisar errores y latencia sin registrar cabeceras, códigos ni cuerpos privados.

No afirmar que sensores, HTTPS del ESP32 o Vercel funcionan de extremo a extremo hasta completar estas comprobaciones reales.
