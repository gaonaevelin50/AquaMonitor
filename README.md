# AquaMonitor

Plataforma Flask + PostgreSQL Neon para temperatura, nivel de agua y turbidez con ESP32.
La versión actual incorpora identidad individual, vinculación por código temporal, sesiones revocables y separación del historial por periodo de propiedad.

**Estado:** implementación local. No se ha migrado Neon de producción, desplegado en Vercel ni cargado firmware al equipo físico.

## Archivos principales

- `app.py`: aplicación Flask, configuración, conexión y cabeceras.
- `aquamonitor_api.py`: usuarios, sesiones, dispositivos, credenciales y lecturas.
- `public/`: dashboard y administración de dispositivos.
- `migrations/001_initial_schema.sql`: esquema inicial conservado.
- `migrations/002_secure_devices.sql`: ampliación de seguridad. Aplicación manual, una sola vez.
- `esp32/aquamonitor_esp32/`: sensores originales y protocolo de red seguro.
- `tests/`: pruebas reales contra PostgreSQL local y pruebas de navegador.
- `docs/DEPLOYMENT.md`: preparación de Vercel, Neon, dominio y certificados.
- `docs/SECURITY.md`: reglas de propiedad y recuperación.
- `docs/VALIDATION.md`: comprobaciones y limitaciones.

## Configuración local

Python 3.13 y las dependencias de `requirements.txt`.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

No sobrescribas `.env`. Consulta `.env.example` para añadir las nuevas variables en el entorno que elijas. El backend necesita `DATABASE_URL`, `SECRET_KEY`, `AQUAMONITOR_PAIRING_PEPPER`, configuración TLS válida y `AQUAMONITOR_DB_SCHEMA_READY=true` **después** de preparar la base correspondiente.

La aplicación nunca ejecuta migraciones. Sin seguridad configurada o sin migración 002, devuelve `503` y no acepta escrituras de la API. La configuración previa de `.env` no se ha actualizado automáticamente.

Las contraseñas nuevas requieren entre 12 y 128 caracteres. Las cuentas existentes conservan su hash y pueden iniciar sesión. Las sesiones antiguas en localStorage dejan de ser válidas: hay que iniciar sesión de nuevo.

```powershell
.\.venv\Scripts\python.exe -B app.py
```

## Vincular un equipo

1. Instala el firmware preparado solo cuando autorices cargarlo.
2. Configura en tu archivo privado la URL HTTPS real terminada en `/api/lecturas`, la CA raíz del dominio y una contraseña de portal de 8 a 63 caracteres.
3. Conecta a `AquaMonitor-Setup`. El portal pide usuario `aquamonitor` y la contraseña privada del portal.
4. Configura una red de 2.4 GHz con internet. El reloj se sincroniza por NTP antes de TLS.
5. Pulsa brevemente BOOT para activar la vinculación. En la primera configuración se activa automáticamente durante 10 minutos.
6. Consulta `/vinculacion` en el portal local o el código mostrado por Serial. No aparecen credenciales privadas.
7. Inicia sesión en AquaMonitor, abre Dispositivos y añade el equipo mediante ese código y un nombre.

El celular que consulta el dashboard y el ESP32 pueden estar en redes distintas. El portal local requiere proximidad al equipo. Mantener BOOT más de 3 segundos borra únicamente la red WiFi; no libera propiedad ni borra la identidad segura.

## Revocación, recuperación y transferencia

- **Revocar envíos:** detiene la credencial de medición; conserva equipo e historial en la cuenta.
- **Autorizar recuperación:** el ESP32 dispone de 10 minutos para registrar una credencial nueva mediante su canal de configuración. Nunca se entrega al navegador.
- **Liberar para transferencia:** cierra el periodo de propiedad y revoca envíos. La nueva persona necesita acceso físico para obtener un código nuevo. El historial anterior permanece únicamente en la cuenta anterior.
- **Bloquear identidad:** revoca también el canal de configuración. Es una acción excepcional que requiere reprovisionamiento físico; no hay desbloqueo por MAC ni por código antiguo.

Consulta las reglas y límites en `docs/SECURITY.md`.

## Pruebas sin Neon

Las pruebas están fijadas al clúster desechable de `127.0.0.1:55439`, usuario `aquamonitor_test`. No usan `DATABASE_URL` para sus conexiones. Si ese clúster no existe, fallan sin buscar otra base.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Cada ejecución crea una base nueva y conserva sus resultados para revisión. Instrucciones completas en `docs/VALIDATION.md`.

El simulador nuevo usa el mismo protocolo individual:

```powershell
.\.venv\Scripts\python.exe -B simulador_esp32.py --host http://127.0.0.1:5000 --pair
```

Guarda secretos de prueba en `.test-runtime/simulator-identity.json`, excluido de Git. No publiques ese archivo. No ejecutes el simulador contra producción sin autorización.
