/*
  AquaMonitor - ESP32: temperatura (DS18B20) + nivel de agua (HC-SR04)

  Es tu código original con dos añadidos:
    - WiFi:      envía las lecturas al servidor en Vercel (por HTTPS) cada 5 s.
                 La red WiFi NO va escrita en el código: se elige desde el celular (ver abajo).
    - Bluetooth: el panel se conecta directo al ESP32 (BLE) y recibe las lecturas.
  Puedes usar uno, el otro o los dos a la vez (ver USAR_WIFI y USAR_BLE).
  Sigue mostrando todo en el Monitor Serie a 115200, como antes.

  LIBRERÍAS (Arduino IDE > Administrar bibliotecas):
    - OneWire
    - DallasTemperature
    - WiFiManager  (autor: tzapu)
  (WiFi, HTTPClient, WiFiClientSecure y BLE ya vienen con el soporte de la placa ESP32.)

  IMPORTANTE - si usas WiFi y Bluetooth a la vez, el programa es grande:
    Herramientas > Partition Scheme > "Huge APP (3MB No OTA/1MB SPIFFS)"
    Si no, Arduino dirá "Sketch too big" (el programa es demasiado grande).

  CÓMO ELEGIR LA RED WIFI (sin volver a programar):
    1. Enciende el ESP32. Si no conoce ninguna red, crea el WiFi "AquaMonitor-Setup" (clave: aquamonitor).
    2. Con el celular conéctate a ese WiFi. Se abre una página (si no, entra a 192.168.4.1).
    3. Pulsa "Configure WiFi", elige tu red (o el punto de acceso de tu celular), escribe la clave y guarda.
    4. El ESP32 recuerda la red. Si lo llevas a otro lugar y no la encuentra, vuelve a abrir
       "AquaMonitor-Setup" solo para que le pongas la nueva red.
    Para borrar la red guardada: mantén pulsado el botón BOOT del ESP32 por 3 segundos.
    Solo funcionan redes de 2.4 GHz con internet (no sirven las que piden iniciar sesión en una página).

  CABLEADO (el mismo de tu código):
    DS18B20  -> GPIO 4  (con resistencia de 4.7 kΩ entre DATA y 3.3 V)
    HC-SR04  -> TRIG GPIO 5, ECHO GPIO 18
  ⚠ El pin ECHO del HC-SR04 saca 5 V y el ESP32 trabaja a 3.3 V:
    usa un divisor de voltaje (por ejemplo 1 kΩ + 2 kΩ) en ECHO.
*/

#include <OneWire.h>
#include <DallasTemperature.h>

// ============================================================
// ===== CONFIGURACIÓN (lo que normalmente debes cambiar) =====
// ============================================================

#define USAR_WIFI 1      // 1 = enviar al servidor por WiFi, 0 = no
#define USAR_BLE  1      // 1 = permitir conexión por Bluetooth desde el panel, 0 = no

// --- Servidor (solo si USAR_WIFI = 1). La red WiFi se elige desde el celular, no aquí ---
// Dirección pública de tu proyecto en Vercel (termina en /api/lecturas).
// Así el ESP32 puede estar en CUALQUIER red WiFi con internet.
const char* SERVER_URL = "https://TU-PROYECTO.vercel.app/api/lecturas";
const char* API_KEY    = "AQUAMONITOR_API_KEY_PLACEHOLDER";   // la MISMA que AQUAMONITOR_API_KEY en Vercel
const unsigned long INTERVALO_ENVIO_WIFI_MS = 5000; // cada cuánto se envía al servidor

// --- Nivel de agua: MIDE con una regla y cambia estos dos valores (en cm) ---
const float DIST_SENSOR_FONDO_CM = 30.0;   // distancia del sensor al fondo (estanque VACÍO = 0 %)
const float DIST_SENSOR_LLENO_CM = 5.0;    // distancia del sensor al agua cuando está LLENO (100 %)

// --- Cada cuánto se lee y se muestra (antes era delay(2000)) ---
const unsigned long INTERVALO_LECTURA_MS = 2000;

// --- Pines (los de tu código) ---
const int pinDatosDS18B20 = 4;   // DS18B20 (temperatura)
const int trigPin = 5;           // HC-SR04 TRIG
const int echoPin = 18;          // HC-SR04 ECHO (con divisor de voltaje)

// ============================================================
// FIN DE LA CONFIGURACIÓN
// ============================================================

#if USAR_WIFI
  #include <WiFi.h>
  #include <WiFiManager.h>
  #include <WiFiClientSecure.h>
  #include <HTTPClient.h>
#endif

#if USAR_BLE
  #include <BLEDevice.h>
  #include <BLEServer.h>
  #include <BLEUtils.h>
  #include <BLE2902.h>
  // Deben ser iguales a los de static/script.js
  #define BLE_SERVICE_UUID "a9e30001-6c1b-4a4e-9a31-5f0b7c2d8e10"
  #define BLE_CHAR_UUID    "a9e30002-6c1b-4a4e-9a31-5f0b7c2d8e10"
  BLECharacteristic* bleChar = nullptr;
  bool bleConectado = false;
#endif

const int16_t SIN_DATO = 0x7FFF;   // valor que significa "este sensor no responde"

OneWire oneWire(pinDatosDS18B20);
DallasTemperature sensors(&oneWire);

unsigned long ultimaLectura = 0;
unsigned long ultimoEnvioWifi = 0;

// ---------- Lectura de sensores ----------
bool leerTemperatura(float &temperaturaC) {
  sensors.requestTemperatures();
  temperaturaC = sensors.getTempCByIndex(0);
  // -127 significa "sensor desconectado"
  return temperaturaC != DEVICE_DISCONNECTED_C && temperaturaC > -50 && temperaturaC < 100;
}

// Devuelve la distancia del sensor a la superficie del agua, en cm (-1 si no hay eco).
// Hace 5 mediciones y usa la mediana para ignorar lecturas erróneas.
float leerDistanciaCm() {
  float medidas[5];
  int n = 0;
  for (int i = 0; i < 5; i++) {
    digitalWrite(trigPin, LOW);
    delayMicroseconds(2);
    digitalWrite(trigPin, HIGH);          // pulso de 10 microsegundos en TRIG
    delayMicroseconds(10);
    digitalWrite(trigPin, LOW);

    long duracion = pulseIn(echoPin, HIGH, 30000);   // máximo 30 ms (~5 m)
    if (duracion > 0) {
      medidas[n++] = duracion * 0.0343 / 2.0;        // 343 m/s = 0.0343 cm/us
    }
    delay(30);
  }
  if (n == 0) return -1;

  for (int i = 1; i < n; i++) {           // ordenar de menor a mayor
    float x = medidas[i];
    int j = i - 1;
    while (j >= 0 && medidas[j] > x) { medidas[j + 1] = medidas[j]; j--; }
    medidas[j + 1] = x;
  }
  return medidas[n / 2];
}

// ---------- Bluetooth ----------
#if USAR_BLE
class CallbacksBle : public BLEServerCallbacks {
  void onConnect(BLEServer* servidor) { bleConectado = true; }
  void onDisconnect(BLEServer* servidor) {
    bleConectado = false;
    BLEDevice::startAdvertising();   // vuelve a quedar visible para reconectar
  }
};

void iniciarBle() {
  char sufijo[5];
  snprintf(sufijo, sizeof(sufijo), "%04X", (uint16_t)(ESP.getEfuseMac() >> 32));
  String nombre = String("AquaMonitor-") + sufijo;

  BLEDevice::init(nombre.c_str());
  BLEServer* servidor = BLEDevice::createServer();
  servidor->setCallbacks(new CallbacksBle());

  BLEService* servicio = servidor->createService(BLE_SERVICE_UUID);
  bleChar = servicio->createCharacteristic(
      BLE_CHAR_UUID, BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  bleChar->addDescriptor(new BLE2902());

  uint8_t vacio[8];
  for (int i = 0; i < 4; i++) { vacio[2 * i] = SIN_DATO & 0xFF; vacio[2 * i + 1] = (SIN_DATO >> 8) & 0xFF; }
  bleChar->setValue(vacio, 8);

  servicio->start();
  BLEAdvertising* anuncio = BLEDevice::getAdvertising();
  anuncio->addServiceUUID(BLE_SERVICE_UUID);
  anuncio->setScanResponse(true);
  BLEDevice::startAdvertising();
  Serial.println("Bluetooth listo. Nombre: " + nombre);
}

// Paquete de 8 bytes: temperatura x10, nivel x10, turbidez x10, pH x100 (cada uno en 16 bits).
// Turbidez y pH todavía no están conectados: se envían como "sin dato".
void enviarPorBle(float temp, bool tempOk, float nivel, bool nivelOk) {
  if (bleChar == nullptr) return;
  int16_t valores[4] = {
    tempOk ? (int16_t)lround(temp * 10) : SIN_DATO,
    nivelOk ? (int16_t)lround(nivel * 10) : SIN_DATO,
    SIN_DATO,
    SIN_DATO
  };
  uint8_t paquete[8];
  for (int i = 0; i < 4; i++) {
    uint16_t v = (uint16_t)valores[i];
    paquete[2 * i] = v & 0xFF;
    paquete[2 * i + 1] = (v >> 8) & 0xFF;
  }
  bleChar->setValue(paquete, 8);        // queda guardado para quien se conecte
  if (bleConectado) bleChar->notify();  // y se envía a quien ya está conectado
}
#endif

// ---------- WiFi ----------
#if USAR_WIFI
WiFiManager wm;
const char* AP_NOMBRE = "AquaMonitor-Setup";   // WiFi que crea el ESP32 para configurarlo
const char* AP_CLAVE  = "aquamonitor";         // su clave (mínimo 8 caracteres)
const int PIN_BOTON_BOOT = 0;                  // botón BOOT del ESP32
unsigned long wifiCaidoDesde = 0;
unsigned long botonDesde = 0;
bool wifiEstabaConectado = false;

void avisoPortalAbierto(WiFiManager* gestor) {
  Serial.println();
  Serial.println("*** CONFIGURA EL WIFI ***");
  Serial.println("1) Con tu celular conectate al WiFi: AquaMonitor-Setup (clave: aquamonitor)");
  Serial.println("2) Se abre una pagina (si no, entra a 192.168.4.1) > Configure WiFi");
  Serial.println("3) Elige tu red, escribe la clave y guarda.");
}

void conectarWifi() {
  WiFi.mode(WIFI_STA);
  wm.setDebugOutput(false);
  wm.setConnectTimeout(20);            // segundos intentando con la red guardada
  wm.setConfigPortalTimeout(180);      // el portal se cierra solo a los 3 minutos
  wm.setConfigPortalBlocking(false);   // el ESP32 sigue midiendo mientras tanto
  wm.setAPCallback(avisoPortalAbierto);
  Serial.println("Conectando a la ultima red WiFi guardada...");
  if (!wm.autoConnect(AP_NOMBRE, AP_CLAVE)) {
    Serial.println("No hay red guardada o no esta disponible: configurala desde el celular.");
  }
}

// Se llama en cada vuelta del loop: atiende el portal, avisa cambios y reabre el portal si hace falta.
void gestionarWifi() {
  wm.process();

  bool conectado = (WiFi.status() == WL_CONNECTED);
  if (conectado && !wifiEstabaConectado) {
    Serial.println("WiFi OK. Red: " + WiFi.SSID() + "  IP del ESP32: " + WiFi.localIP().toString());
  }
  wifiEstabaConectado = conectado;

  if (conectado) {
    wifiCaidoDesde = 0;
  } else {
    if (wifiCaidoDesde == 0) wifiCaidoDesde = millis();
    // Sin WiFi por más de 60 s: vuelve a abrir "AquaMonitor-Setup" para poder elegir otra red
    if (!wm.getConfigPortalActive() && millis() - wifiCaidoDesde > 60000) {
      Serial.println("Sin WiFi hace un minuto, abriendo AquaMonitor-Setup...");
      wm.startConfigPortal(AP_NOMBRE, AP_CLAVE);
      wifiCaidoDesde = millis();
    }
  }

  // Botón BOOT mantenido 3 s: borra la red guardada y reinicia
  if (digitalRead(PIN_BOTON_BOOT) == LOW) {
    if (botonDesde == 0) botonDesde = millis();
    if (millis() - botonDesde > 3000) {
      Serial.println("Borrando la red WiFi guardada y reiniciando...");
      wm.resetSettings();
      delay(300);
      ESP.restart();
    }
  } else {
    botonDesde = 0;
  }
}

void enviarPorWifi(float temp, bool tempOk, float nivel, bool nivelOk) {
  if (!tempOk && !nivelOk) return;   // no hay nada que enviar

  String json = "{\"mac\":\"" + WiFi.macAddress() + "\",\"rssi\":" + String(WiFi.RSSI());
  if (tempOk) json += ",\"temperatura\":" + String(temp, 1);
  if (nivelOk) json += ",\"nivel_agua\":" + String(nivel, 1);
  json += "}";

  WiFiClientSecure cliente;
  cliente.setInsecure();   // HTTPS sin validar el certificado (suficiente para este proyecto)

  HTTPClient http;
  http.begin(cliente, SERVER_URL);
  http.setTimeout(8000);   // HTTPS tarda un poco más que HTTP
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);
  int codigo = http.POST(json);
  if (codigo == 200) {
    Serial.println("  -> Enviado al servidor por WiFi");
  } else {
    Serial.printf("  -> Error al enviar por WiFi (codigo %d): %s\n", codigo, http.getString().c_str());
  }
  http.end();
}
#endif

// ---------- Programa principal ----------
void setup() {
  Serial.begin(115200);

  // Inicializar sensor de temperatura
  sensors.begin();

  // Inicializar pines del sensor ultrasónico
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);

#if USAR_BLE
  iniciarBle();
#endif
#if USAR_WIFI
  pinMode(PIN_BOTON_BOOT, INPUT_PULLUP);
  conectarWifi();
#endif
}

void loop() {
#if USAR_WIFI
  gestionarWifi();
#endif

  if (millis() - ultimaLectura < INTERVALO_LECTURA_MS) return;
  ultimaLectura = millis();

  // 1. Leer temperatura del agua
  float temperaturaC = 0;
  bool tempOk = leerTemperatura(temperaturaC);

  // 2. Leer distancia a la superficie y convertirla a porcentaje de nivel
  float distanciaCm = leerDistanciaCm();
  bool nivelOk = distanciaCm >= 0;
  float nivelPct = 0;
  if (nivelOk) {
    nivelPct = (DIST_SENSOR_FONDO_CM - distanciaCm) / (DIST_SENSOR_FONDO_CM - DIST_SENSOR_LLENO_CM) * 100.0;
    nivelPct = constrain(nivelPct, 0.0, 100.0);
  }

  // 3. Mostrar resultados en el Monitor Serie
  Serial.print("Temp. del agua: ");
  if (tempOk) { Serial.print(temperaturaC); Serial.print(" °C  |  "); }
  else        { Serial.print("sin dato  |  "); }
  Serial.print("Distancia a la superficie: ");
  if (nivelOk) {
    Serial.print(distanciaCm);
    Serial.print(" cm  |  Nivel: ");
    Serial.print(nivelPct, 1);
    Serial.println(" %");
  } else {
    Serial.println("sin eco (revisa el sensor)");
  }

  // 4. Enviar
#if USAR_BLE
  enviarPorBle(temperaturaC, tempOk, nivelPct, nivelOk);
#endif
#if USAR_WIFI
  if (WiFi.status() == WL_CONNECTED && millis() - ultimoEnvioWifi >= INTERVALO_ENVIO_WIFI_MS) {
    ultimoEnvioWifi = millis();
    enviarPorWifi(temperaturaC, tempOk, nivelPct, nivelOk);
  }
#endif
}
