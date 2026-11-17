# Auditoría y actualización controlada del nivel

## Causa demostrada

La lectura física capturada por USB tres veces fue 8,11 cm y 87,6 %.
Coincide con `(30-8.11)/(30-5)*100 = 87.56`, redondeado a una cifra.
Por tanto la placa todavía ejecuta la referencia anterior de 30/5 cm.
La referencia provisional autorizada de 7,8/2,0 ya estaba preparada en el código,
pero no se ha cargado en el ESP32. Con ella 8,11 cm se limita a 0 %.

La consulta de solo lectura sobre el ESP32 conocido en Neon pruebas encontró
un registro histórico de 95 % y lecturas actuales de 87,6 %, coincidentes con
Serial. No se recuperó una distancia histórica para el 95 %: nunca se almacenó.
No se presenta una distancia invertida matemáticamente como si fuera medida.
Las credenciales y datos identificadores privados no se publican en el informe.

## Recorrido completo

1. HC-SR04: cinco ecos en centímetros, mediana y rechazo de ecos inválidos.
2. Firmware: único cálculo `(7.8-distancia)/(7.8-2.0)*100`, limitado a 0–100.
3. JSON: nivel_agua contiene porcentaje, distancia_cm contiene la mediana en cm
   y nivel_calibracion identifica `provisional-7.8-2.0`. No contiene credenciales
   en el cuerpo ni muestra cabeceras Bearer en registros.
4. Neon: recibe el porcentaje sin recalcularlo. La migración 003 preparada agrega
   dos columnas nullable, sin borrar ni reescribir históricos; registros anteriores
   mantienen distancia y calibración desconocidas. No se ejecutó la migración.
5. API/dashboard: el número recibido se valida como finito y entre 0 y 100, sin
   calcularlo desde la distancia. La API evalúa también la edad de la lectura,
   no solo ultima_conexion. El frontend descarta lecturas de más de 30 segundos,
   las borra al fallar la consulta y tiene un reloj local de vencimiento por si
   una solicitud queda pendiente. No modifica la autenticación.
6. Dibujo: height equivale al porcentaje validado. La ola antes sobresalía 11 px;
   ahora queda dentro de la superficie del agua. Un 95 % ya no se dibuja como
   95 % más una franja decorativa fuera del nivel.

El paquete BLE existente de ocho bytes se conserva y no transmite distancia.
Si el dashboard recibe por Bluetooth, indica distancia no disponible y referencia
sin identificar; no mezcla esa lectura con la de otro dispositivo WiFi ni inventa cm.
La distancia del montaje sigue visible en Serial. La nueva trazabilidad almacenada
requiere el flujo WiFi/API descrito arriba.

## Compatibilidad y actualización controlada

- Usuarios, sesiones, cookies, CSRF, propiedad, historial, WiFi y TLS se conservan.
- Los clientes antiguos sin metadatos continúan usando el INSERT de seis campos.
- La consulta nueva usa to_jsonb para seguir leyendo con esquema 002; se probó
  en modo de solo lectura sobre pruebas antes de migrar.
- Un cliente nuevo que envíe metadatos antes de la 003 recibe 503 explícito;
  no se descarta silenciosamente la distancia.
- Revisar y autorizar primero `migrations/003_level_trace.sql` exclusivamente en
  pruebas. Después publicar backend y frontend en Preview y reiniciar el servidor
  local si se usará localhost. Confirmar compatibilidad con lecturas anteriores.
- Solo entonces, con autorización expresa, cargar el binario nuevo en el ESP32.
  Verificar la misma medición en Serial, JSON, fila nueva de Neon y dashboard.
  Ni cambiar archivos locales ni desplegar la web sustituye cargar el firmware.

## Pruebas

- C++: 0/50/100, límites, ecos inválidos, mediana y referencia provisional.
- Diez pruebas Python: recepción sin recálculo, distancia inválida, 503 sin esquema,
  edad de lectura, historial, dashboard y regresiones de registro/sesión/CSRF/TLS.
- Chrome con todas las API simuladas: altura real del dibujo 0/50/95/100, distancia
  2,29 cm recibida, ausencia de desbordamiento de ola y borrado por error/caducidad.
- SQL 003 preparado; ejecución temporal local no comprobada porque el clúster local
  estaba apagado. No se inició ni se ejecutó sobre Neon.
- Compilación ESP32 Dev Module / Huge APP correcta: 1 456 748 bytes (46 %),
  variables globales 60 420 bytes (18 %). No se ha cargado al dispositivo.

Resultados locales: `.test-runtime/level-trace-audit.json` y
`.test-runtime/level-trace-ready.json`. Estado preparado; sin despliegue,
sin migración real, sin carga de firmware, sin cambios en Production.


## Actualización local posterior: calidad DS18B20 y migración opcional

El estado vigente está en `CONTROLLED_SENSOR_UPDATE.md`. La 003 ya no bloquea
las mediciones principales: es opcional para persistir distancia y diagnósticos.
La compatibilidad con 002 y la conservación de históricos fueron probadas en
PostgreSQL local. El firmware y la web siguen sin cargarse/desplegarse.
