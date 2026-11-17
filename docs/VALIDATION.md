# Validación de la implementación

Fecha: 16 de noviembre de 2026. Pruebas locales, sin conexiones ni escrituras a Neon durante esta etapa.

## Resultados

| Comprobación | Resultado |
| --- | --- |
| Suite Python/PostgreSQL | 19 pruebas aprobadas en la ejecución final. |
| Migraciones 001 y 002 | Aplicadas únicamente a bases locales nuevas; conservación de propietario y lectura antigua comprobada antes de las pruebas. |
| Doble reclamación concurrente | Una vinculación 201 y otra 409; una sola asignación abierta. |
| Revocación con recepción concurrente | La recepción espera el bloqueo y revalida la credencial; no guarda datos tras quedar revocada. |
| Transferencia | Credenciales antiguas rechazadas; periodos e historiales separados entre cuentas. |
| Renovación | Reintentos idempotentes, caducidad y rechazo de generaciones revocadas o de otra asignación. |
| Protección de sesión | CSRF, cookie HttpOnly/SameSite, revocación por logout y configuración Secure en producción comprobadas. |
| Entradas | JSON incorrecto, booleanos, NaN, enteros enormes, rangos y campos de identidad inyectados rechazados. |
| Historial | Paginación 100+5 comprobada; datos sin asignación histórica excluidos. |
| Navegador | Chrome local sin ventana: registro, vinculación, lecturas, historial, revocación, recuperación, liberación, vista móvil y logout aprobados; sin errores JavaScript de página. |
| Proxy Vercel | Esquema HTTPS de proxy administrado comprobado mediante prueba local. |
| Firmware final | Compilación aprobada con WiFi y BLE habilitados, ESP32 3.3.11 y Huge APP. |
| Tamaño del firmware | 1 929 903 bytes de programa, 61 % de 3 145 728 disponibles; 65 244 bytes globales, 19 %. |
| Sensores | Pines, calibraciones y parámetros verificados; funciones de sensores y bloque de adquisición comparados exactamente con la copia anterior a los cambios. |
| TLS ESP32 | `setCACert(ROOT_CA_CERT)` conservado; sin `setInsecure()`. |
| Sintaxis | Python, JavaScript y JSON de Vercel correctos; `pip check` y `git diff --check` sin errores. |

La prueba de navegador utiliza credenciales de dispositivo solo en el proceso Node de pruebas; nunca las introduce en el contexto de la página. Se corrigió una espera fija de 400 ms para esperar explícitamente la respuesta confirmada de recuperación.

## Reproducir las pruebas de PostgreSQL

Requiere PostgreSQL local instalado. El helper de Windows usa por defecto `C:\Program Files\PostgreSQL\18\bin`; se puede indicar otro directorio con `-Bin`.

```powershell
.\tools\local_postgres.ps1 -Action start
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\tools\local_postgres.ps1 -Action stop
```

El clúster está dentro de `.test-runtime/postgres-data`, escucha únicamente en `127.0.0.1:55439` y contiene solo datos ficticios. Usa autenticación local trust exclusivamente para esas pruebas; no reutilizarlo con datos privados ni exponer el puerto.

El helper exige una marca para controlar un clúster existente. No toca servicios PostgreSQL del sistema. Cada suite crea una base `aquamonitor_test_*` nueva; las conserva para inspección y nunca cae a `DATABASE_URL` si falta el clúster.

## Reproducir el navegador

Con el clúster local de pruebas activo, instalar Playwright solo en el directorio excluido:

```powershell
npm install --prefix .test-runtime/ui playwright --no-audit --no-fund
.\.venv\Scripts\python.exe -B tools/local_preview.py
```

Desde otra terminal:

```powershell
node tests/browser_e2e.cjs
```

Usa Chrome ya instalado; no descarga un navegador. `tools/local_preview.py` crea otra base local desechable y secretos efímeros sin modificar `.env`. La captura móvil queda en `.test-runtime/dashboard-mobile.png`. Detener el servidor con Ctrl+C y el clúster con el helper al terminar.

## Reproducir la compilación

Dependencias usadas: ESP32 core 3.3.11, WiFiManager 2.0.17, OneWire y DallasTemperature instaladas localmente, ArduinoJson 7.4.3. La CLI se localizó dentro de Arduino IDE. Si cambia la instalación, indicar `-Cli`.

```powershell
.\tools\check_firmware.ps1
```

El helper copia el código a `.test-runtime/firmware/`, sustituye únicamente el archivo de la copia por la plantilla pública vacía y compila con dos tareas. Nunca lee ni modifica `esp32/aquamonitor_esp32/secrets.h` ni ejecuta un comando de carga. Los binarios son artefactos de comprobación sin configuración privada; no son un firmware listo para conectar a producción.

## Límites de la verificación

- No se ha ejecutado migración alguna en Neon ni probado esta versión contra la base de producción.
- No se ha ejecutado build ni despliegue de Vercel. Falta comprobar el runtime real, certificados de Neon, variables y rutas CDN/API en un entorno autorizado.
- No se ha cargado firmware; quedan pendientes sensores físicos, portal en un celular, NVS ante cortes eléctricos, NTP y TLS real del ESP32 hacia el dominio final.
- No hay almacenamiento persistente de muestras durante cortes de internet; se conservan identidad y operaciones de configuración, no todas las mediciones offline.
- Las lecturas históricas previas a 002 se conservan sin asignación y no se adjudican automáticamente a cuentas.
- BLE mantiene su lectura local previa, sin autenticación de propietario; no da acceso a historial ni credenciales de la nube.

Los archivos originales no secretos se copiaron a `.audit-backups/` antes de modificarlos. Las copias, bases, capturas y binarios están excluidos de Git y del paquete de despliegue.
