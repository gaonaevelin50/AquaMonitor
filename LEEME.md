# AquaMonitor en Vercel — funciona desde cualquier red WiFi

El panel (diseño y funciones) es EXACTAMENTE el mismo. Lo único que cambió es lo de "atrás":

```
ESP32 --(WiFi cualquiera + internet)--> https://tu-proyecto.vercel.app <--- tu celular / PC (cualquier red o datos)
                                              |
                                        Base de datos PostgreSQL (Neon)
```

El ESP32 y tú ya no tienen que estar en la misma red: los dos solo necesitan internet.

## Qué cambió (y qué no)
- `public/` (index.html, styles.css, script.js): **idéntico**, ni una línea cambiada.
- `app.py`: ahora usa PostgreSQL en vez de SQLite (Vercel borra los archivos locales, SQLite perdería todo).
  Mismas rutas, mismas respuestas, mismo login y mismo bloqueo tras 5 intentos.
- `.ino`: ahora envía por HTTPS a tu URL de Vercel (única parte que debes editar: WiFi, URL y API key).

## 1. Subir a Vercel
1. Sube la carpeta a un repositorio de GitHub (el `.gitignore` ya viene listo).
2. En vercel.com: **Add New > Project** > elige el repositorio > **Deploy**
   (Vercel detecta Flask solo; no pongas build command).
3. Ya en el proyecto: **Storage > Create Database > Neon (Postgres)** y conéctalo al proyecto.
   Eso crea solo la variable `DATABASE_URL`.
4. **Settings > Environment Variables**, agrega:
   - `SECRET_KEY` = VALOR_DE_EJEMPLO
   - `AQUAMONITOR_API_KEY` = VALOR_DE_EJEMPLO
5. **Deployments > Redeploy** para que tome las variables.
6. Abre `https://tu-proyecto.vercel.app`, crea tu cuenta y listo. Las tablas se crean solas.

## 2. ESP32
En `esp32/aquamonitor_esp32/aquamonitor_esp32.ino` cambia:
- `WIFI_SSID` / `WIFI_PASS`: la red donde esté el ESP32 (puede ser otra distinta a la tuya).
- `SERVER_URL`: `https://tu-proyecto.vercel.app/api/lecturas`
- `API_KEY`: la misma que pusiste en `AQUAMONITOR_API_KEY`.
Lo demás (pines, Partition Scheme "Huge APP", niveles) igual que antes.

## 3. Vincular
**Dispositivos > Vincular por WiFi**, con el ESP32 prendido. Vincúlalo apenas aparezca:
mientras no tiene dueño, cualquier usuario registrado lo ve en la lista por 2 minutos.

## Bluetooth
Sigue funcionando igual (solo cerca del ESP32, en Chrome/Edge). Ventaja nueva: Vercel usa HTTPS,
así que en Android ya NO necesitas el truco de `chrome://flags`.

## Probar sin ESP32
`python simulador_esp32.py --host https://tu-proyecto.vercel.app --key TU_API_KEY`

## Correr en tu PC (opcional)
Necesitas una `DATABASE_URL` (la misma de Neon sirve):
```
pip install -r requirements.txt
set DATABASE_URL=postgresql://...        (en PowerShell: $env:DATABASE_URL="postgresql://...")
python app.py
```

## Problemas comunes
- **Error 500 en Vercel:** falta `DATABASE_URL` o `SECRET_KEY`; agrégalas y haz Redeploy.
- **Código 401 en el Monitor Serie:** `API_KEY` del .ino distinta a `AQUAMONITOR_API_KEY`.
- **Código -1 en el Monitor Serie:** el ESP32 no tiene internet o `SERVER_URL` está mal escrita.
- **El ESP32 no aparece al vincular:** debe estar enviando datos (mira "Enviado al servidor" en el Monitor Serie).
