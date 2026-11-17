# Nivel verificable y recuperación del indicador original — corrección local

## Diagnóstico del 87,6 %

La lectura física auditada fue 8,11 cm -> 87,6 %. Es el resultado de la referencia
30/5 de la versión anterior todavía cargada: `(30-8.11)/(30-5)*100 = 87.56`.
Con la referencia acordada 7,8/2,0, el firmware preparado daría 0 % al limitar
su resultado. La sonda de turbidez no participa en este cálculo.

El firmware anterior envía nivel_agua pero no distancia_cm ni nivel_calibracion.
Además, el esquema 002 no tiene columnas para persistir esos metadatos: aun si
un firmware nuevo los envía, el backend compatible conserva solo el núcleo de
mediciones e informa trazabilidad_guardada=false. La consulta posterior no puede
recuperar una distancia que nunca se guardó. No se deduce una distancia del 87,6 %.

La web anterior comprobaba únicamente que el porcentaje fuera numérico entre
0 y 100 y reciente. Por eso mostraba 87,6 incluso al advertir que faltaba referencia.
La recepción reciente no convierte un porcentaje con calibración incorrecta en
una lectura físicamente válida.

## Corrección local

`level_quality.py` valida distancia finita entre 2 y 400 cm, referencia exacta
provisional-7.8-2.0 y porcentaje finito entre 0 y 100. Verifica la correspondencia
usando la relación inversa en centímetros, con margen de serialización de
0,0099 cm. No genera, redondea ni sustituye el porcentaje: solo acepta o rechaza
el recibido. El cálculo de porcentaje sigue exclusivamente en el firmware.

La API de última lectura devuelve nivel_agua=null cuando falta evidencia o la
referencia no coincide. El valor bruto queda como diagnóstico nivel_agua_recibido
y en el historial original. Ninguna fila se reescribe. El dashboard exige el
estado validado por el backend y los metadatos; no usa el valor diagnóstico para
llenar el tanque. Tampoco muestra cero cuando falta una lectura: usa --, la frase
«Sin lectura válida de nivel de agua» y un recipiente sin agua con aviso visible.
Un cero real validado sí aparece como 0,0 %, distinto del estado desconocido.

El paquete BLE actual tampoco incluye distancia/referencia; se oculta solo su
nivel no verificable, manteniendo temperatura, turbidez y conexión.

## Diseño recuperado de Git

La forma, SVG de ola, colores y animación aparecen desde 71522bd (Initial commit)
y se conservan en 0c1f4eb, 8c2652c y 563ca98 (version 4), así como en los respaldos.
La referencia comparada en pruebas fue 563ca98:public/styles.css.

Se recuperaron el SVG original, degradado #58CFC6 -> #1B7F8A, radio de recipiente
18 px, movimiento de ola de 6 segundos y transición de altura de 0,9 segundos.
Mover la ola dentro de un bloque ya opaco la había hecho parecer plana. Ahora la
capa transparente de superficie y el cuerpo de agua son independientes dentro de
un contenedor cuya altura es el porcentaje recibido. La ola permanece visible y
no agrega altura artificial al porcentaje. No se cambiaron estilos fuera del
bloque del agua ni las tarjetas de temperatura, turbidez o WiFi.

Capturas de revisión con datos de prueba, no mediciones físicas:
- `.test-runtime/water-git-reference-71_2.png`
- `.test-runtime/water-restored-71_2.png`
- `.test-runtime/water-no-valid-reading.png`

## Pruebas y conservación

22 pruebas Python específicas aprobadas, prueba C++ existente del cálculo y
filtrado aprobada, y navegador Chrome con todas las API interceptadas aprobado.
Casos 0/50/71,2/95/100, falta de distancia, referencia 30/5, combinación
incompatible, 0 sin evidencia, caducidad, errores de red y temperatura.
Se comprobó que un 71,2 validado se conserva exactamente, no se recalcula.

Las consultas de Neon fueron exclusivamente de solo lectura: las 976 filas
históricas protegidas conservaron sus huellas. Se observaron 1099 filas totales
al comprobarlas; los nuevos envíos del dispositivo pueden seguir agregándose,
pero esta corrección no hizo INSERT, UPDATE ni DELETE en Neon. La versión sigue
siendo 002. Firmware, secrets.h, .env, autenticación, sesiones e historial no se
modificaron. No se ejecutó la 003 ni siquiera en pruebas locales de esta etapa.
No se desplegó ni se cargó firmware.

## Qué falta para una medición física verificable

1. Revisar y autorizar posteriormente la publicación del backend y frontend.
   Incluir el nuevo módulo level_quality.py en la copia de publicación.
2. Autorizar una futura carga de firmware con 7,8/2,0 y envío de distancia real
   del HC-SR04 y referencia; confirmar antes que apunta al backend actualizado.
3. Resolver el almacenamiento/retorno de distancia y referencia de la misma
   muestra. Con esquema 002 actual no se recuperan en el GET y el nivel quedará
   intencionadamente no disponible. La 003 preparada es una posible solución,
   pero NO se ejecutó ni se autoriza aquí; cualquier alternativa requiere revisión.
   Bajo esta condición estricta, guardar solo porcentaje ya no basta para mostrarlo.
4. Contrastar físicamente vacío, punto intermedio y máximo, con la misma distancia
   en Serial/JSON/API. No convertir la altura de la sonda de turbidez en el máximo.

## Archivos de esta etapa

- level_quality.py (nuevo), aquamonitor_api.py.
- public/script.js, public/index.html, public/styles.css.
- tests/test_level_provenance.py, tests/test_level_trace.py,
  tests/test_level_contract.py y tests/level_dashboard_e2e.cjs.
- Esta guía. Resultados: `.test-runtime/level-validity-wave-result.json`.

Los cambios son locales: la URL Vercel anterior no incluye esta corrección aún.

## Actualización autorizada: migración 003 en Pruebas (2026-11-17)

La migración 003 ya se aplicó exclusivamente al endpoint Neon Pruebas
previamente confirmado por el usuario. Se contrastaron DATABASE_URL,
NEON_PRUEBAS_HOST y la identidad del endpoint devuelta por PostgreSQL,
con TLS verify-full. No se ejecutaron otras migraciones en Neon.

El registro de versiones contiene 2 y 3. Existen las cuatro columnas
opcionales distancia_cm, nivel_calibracion, temperatura_estado y
temperatura_observada, con sus restricciones validadas. Los datos anteriores
mantienen NULL en esas columnas: no se dedujeron distancias ni se recalculó
ningún porcentaje histórico.

Se verificaron intactas las 1.280 mediciones existentes al aplicar la
migración, incluidas las 976 originales, y todos los demás registros de
usuarios, dispositivos, credenciales, vinculaciones y sesiones. Una inserción
de prueba con distancia 4,9 cm y nivel 50 % se validó dentro de un savepoint
y se revirtió, sin consumir la secuencia ni guardar mediciones ficticias.
También se comprobó que una distancia inválida fuese rechazada.

Validación posterior: 41 pruebas Python aprobadas contra PostgreSQL local,
tres pruebas nativas de sensores aprobadas y prueba visual local aprobada
para 0/50/71,2/95/100, ola original y ocultación de valores sin trazabilidad.
El firmware y el binario previamente compilado conservan sus huellas;
.env y secrets.h no se modificaron.

Este resultado resuelve el paso 3 pendiente descrito arriba. Siguen pendientes
la publicación autorizada del backend/frontend en Preview, comprobar el
destino HTTPS del firmware frente a ese backend y una carga física autorizada.
La migración por sí sola no actualiza la web publicada ni el ESP32: las filas
antiguas sin distancia seguirán sin ser una lectura actual válida de nivel.
No se publicó ningún despliegue ni se cargó firmware durante esta etapa.

Evidencias locales privadas (excluidas de publicación):
`.test-runtime/migration003-result.json`,
`.test-runtime/migration003-postcommit.json` y
`.test-runtime/migration003-backend-tests.log`.
