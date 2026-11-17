# Flujo de actualización y reversión de AquaMonitor

## Ramas y despliegues

- `main` es la versión estable. En el proyecto existente de Vercel, confirmar que es la rama de Production y que su despliegue automático está deshabilitado antes de vincular el repositorio.
- `develop` recibe cambios revisados mediante pull request. Vercel debe desplegar esta rama en Preview. Confirmar rama, SHA, entorno y URL en cada despliegue.
- Validar el dashboard y revisar registros de solicitudes reales del ESP32 y sus mediciones recientes en Neon con consultas de solo lectura. Conservar sesiones, credenciales y migraciones.
- Integrar en `main` la versión validada. Cualquier publicación a Production requiere autorización expresa y una acción manual.

## Cambio de repositorio

1. Crear el repositorio privado y comprobar el contenido de ambas ramas y su historial. Verificar que la aplicación de GitHub de Vercel tiene acceso al repositorio.
2. Registrar los identificadores de los despliegues vigentes y confirmar dominios, proyecto, rama de Production y nombres y ámbitos de variables en Vercel. Mantener los valores en Vercel.
3. Conservar la integración anterior hasta validar el nuevo repositorio. Si hace falta validar un despliegue candidato mientras la integración original sigue conectada, usar el proyecto existente con un despliegue Preview autorizado desde el checkout del repositorio nuevo, tras revisar que su configuración local apunta al proyecto esperado.
4. Vincular el repositorio nuevo al proyecto existente y verificar un Preview originado en `develop`. Si el cambio de vínculo falla, restaurar el repositorio anterior y conservar los despliegues existentes.
5. Conservar la URL del despliegue previo, especialmente si está grabada en el ESP32. Una URL única de despliegue identifica una versión concreta. Usar la URL de rama de `develop` para revisar nuevas versiones y conservar los dominios ya configurados.

## Referencias del entorno verificado

- Proyecto Vercel: rota-smart1/aquamonitor. El dominio asignado es aquamonitor-olive.vercel.app.
- Preview observado: aquamonitor-5ym9reup8-rota-smart1.vercel.app, desplegado originalmente por CLI.
- El sketch local apunta a aquamonitor-ten.vercel.app y envía X-API-Key. La API de la copia web recibe mediciones con Bearer. Confirmar el host y protocolo del equipo físico antes de asumir que usa este Preview. No cambiar el equipo para validar el traslado.

## Reversión

Para revertir código de Preview, identificar el SHA validado en el historial, crear un PR a `develop` que revierta el cambio con `git revert` y verificar el nuevo Preview. Mientras se construye, usar la URL del despliegue Preview anterior. Para un incidente en Production, el propietario puede autorizar la reversión manual en Vercel a un despliegue estable registrado. La reversión de código no incluye cambios en Neon ni en el ESP32.

Referencias: [Entornos de Vercel](https://vercel.com/docs/deployments/environments), [reglas de despliegue Git](https://vercel.com/docs/project-configuration/git-configuration).
