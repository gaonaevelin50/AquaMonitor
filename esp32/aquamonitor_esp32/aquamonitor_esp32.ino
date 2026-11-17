/*
  AquaMonitor - ESP32
  Temperatura DS18B20 + nivel HC-SR04 + turbidez SEN0189
  Conexion WiFi y Bluetooth BLE
*/

#include <OneWire.h>
#include <DallasTemperature.h>
#include <math.h>

// ============================================================
// CONFIGURACION
// ============================================================

#define USAR_WIFI 1
#define USAR_BLE  1

// URL de tu proyecto en Vercel
const char* SERVER_URL = "https://aquamonitor-ten.vercel.app/api/lecturas";

// Debe coincidir exactamente con la clave configurada en tu app.py (por defecto "AQUAMONITOR_API_KEY_PLACEHOLDER")
const char* API_KEY = "AQUAMONITOR_API_KEY_PLACEHOLDER";

const unsigned long INTERVALO_ENVIO_WIFI_MS = 5000;

const float DIST_SENSOR_FONDO_CM = 7.8;
const float DIST_SENSOR_LLENO_CM = 2.0;

// CALIBRACION DE TURBIDEZ
const int ADC_AGUA_CLARA = 2205;  
const int ADC_AGUA_TURBIA = 1000;
const float NTU_MAXIMO = 100.0;

const unsigned long INTERVALO_LECTURA_MS = 2000;

// Pines
const int pinDatosDS18B20 = 4;
const int trigPin = 5;
const int echoPin = 18;
const int pinTurbidez = 34;

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

#define BLE_SERVICE_UUID "a9e30001-6c1b-4a4e-9a31-5f0b7c2d8e10"
#define BLE_CHAR_UUID "a9e30002-6c1b-4a4e-9a31-5f0b7c2d8e10"

BLECharacteristic* bleChar = nullptr;
bool bleConectado = false;
#endif

const int16_t SIN_DATO = 0x7FFF;

OneWire oneWire(pinDatosDS18B20);
DallasTemperature sensors(&oneWire);

unsigned long ultimaLectura = 0;
unsigned long ultimoEnvioWifi = 0;

// ============================================================
// TEMPERATURA
// ============================================================

bool leerTemperatura(float &temperaturaC) {
  sensors.requestTemperatures();
  temperaturaC = sensors.getTempCByIndex(0);

  return temperaturaC != DEVICE_DISCONNECTED_C &&
         temperaturaC > -50 &&
         temperaturaC < 100;
}

// ============================================================
// NIVEL DE AGUA
// ============================================================

float leerDistanciaCm() {
  float medidas[5];
  int n = 0;

  for (int i = 0; i < 5; i++) {
    digitalWrite(trigPin, LOW);
    delayMicroseconds(2);
    digitalWrite(trigPin, HIGH);
    delayMicroseconds(10);
    digitalWrite(trigPin, LOW);

    long duracion = pulseIn(echoPin, HIGH, 30000);

    if (duracion > 0) {
      medidas[n++] = duracion * 0.0343 / 2.0;
    }

    delay(30);
  }

  if (n == 0) return -1;

  for (int i = 1; i < n; i++) {
    float x = medidas[i];
    int j = i - 1;

    while (j >= 0 && medidas[j] > x) {
      medidas[j + 1] = medidas[j];
      j--;
    }

    medidas[j + 1] = x;
  }

  return medidas[n / 2];
}

// ============================================================
// TURBIDEZ
// ============================================================

bool leerTurbidez(int &raw, float &ntu) {
  long suma = 0;
  const int MUESTRAS = 20;

  for (int i = 0; i < MUESTRAS; i++) {
    suma += analogRead(pinTurbidez);
    delay(5);
  }

  raw = suma / MUESTRAS;

  if (raw < 20) {
    ntu = 0;
    return false;
  }

  if (raw >= ADC_AGUA_CLARA) {
    ntu = 0.0;
  } else {
    ntu = ((float)(ADC_AGUA_CLARA - raw) /
           (float)(ADC_AGUA_CLARA - ADC_AGUA_TURBIA))
           * NTU_MAXIMO;
  }

  ntu = constrain(ntu, 0.0, NTU_MAXIMO);

  if (ntu < 1.0) {
    ntu = 0.0;
  }

  return true;
}

// ============================================================
// BLUETOOTH
// ============================================================

#if USAR_BLE

class CallbacksBle : public BLEServerCallbacks {
  void onConnect(BLEServer* servidor) {
    bleConectado = true;
  }

  void onDisconnect(BLEServer* servidor) {
    bleConectado = false;
    BLEDevice::startAdvertising();
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
    BLE_CHAR_UUID,
    BLECharacteristic::PROPERTY_READ |
    BLECharacteristic::PROPERTY_NOTIFY
  );

  bleChar->addDescriptor(new BLE2902());

  uint8_t vacio[8];
  for (int i = 0; i < 4; i++) {
    vacio[2 * i] = SIN_DATO & 0xFF;
    vacio[2 * i + 1] = (SIN_DATO >> 8) & 0xFF;
  }

  bleChar->setValue(vacio, 8);
  servicio->start();

  BLEAdvertising* anuncio = BLEDevice::getAdvertising();
  anuncio->addServiceUUID(BLE_SERVICE_UUID);
  anuncio->setScanResponse(true);

  BLEDevice::startAdvertising();
  Serial.println("Bluetooth listo. Nombre: " + nombre);
}

void enviarPorBle(float temp, bool tempOk,
                  float nivel, bool nivelOk,
                  float turb, bool turbOk) {
  if (bleChar == nullptr) return;

  int16_t valores[4] = {
    tempOk ? (int16_t)lround(temp * 10) : SIN_DATO,
    nivelOk ? (int16_t)lround(nivel * 10) : SIN_DATO,
    turbOk ? (int16_t)lround(turb * 10) : SIN_DATO,
    SIN_DATO
  };

  uint8_t paquete[8];
  for (int i = 0; i < 4; i++) {
    uint16_t v = (uint16_t)valores[i];
    paquete[2 * i] = v & 0xFF;
    paquete[2 * i + 1] = (v >> 8) & 0xFF;
  }

  bleChar->setValue(paquete, 8);
  if (bleConectado) {
    bleChar->notify();
  }
}

#endif

// ============================================================
// WIFI
// ============================================================

#if USAR_WIFI

WiFiManager wm;

const char* AP_NOMBRE = "AquaMonitor-Setup";
const char* AP_CLAVE = "aquamonitor";

const int PIN_BOTON_BOOT = 0;

unsigned long wifiCaidoDesde = 0;
unsigned long botonDesde = 0;
bool wifiEstabaConectado = false;

void avisoPortalAbierto(WiFiManager* gestor) {
  Serial.println();
  Serial.println("*** CONFIGURA EL WIFI ***");
  Serial.println("Conectate a AquaMonitor-Setup");
  Serial.println("Clave: aquamonitor");
  Serial.println("Entra a 192.168.4.1");
}

void conectarWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);

  wm.setDebugOutput(false);
  wm.setConnectTimeout(20);
  wm.setConfigPortalTimeout(180);
  wm.setConfigPortalBlocking(false);
  wm.setAPCallback(avisoPortalAbierto);

  Serial.println("Conectando a la ultima red WiFi guardada...");

  if (!wm.autoConnect(AP_NOMBRE, AP_CLAVE)) {
    Serial.println("Configura la red desde AquaMonitor-Setup.");
  }
}

void gestionarWifi() {
  wm.process();

  bool conectado = (WiFi.status() == WL_CONNECTED);

  if (conectado && !wifiEstabaConectado) {
    Serial.println("WiFi conectado correctamente.");
    Serial.println("Red: " + WiFi.SSID());
    Serial.println("IP: " + WiFi.localIP().toString());
  }

  if (!conectado && wifiEstabaConectado) {
    Serial.println("Se perdio la conexion WiFi.");
  }

  wifiEstabaConectado = conectado;

  if (conectado) {
    wifiCaidoDesde = 0;
  } else {
    if (wifiCaidoDesde == 0) {
      wifiCaidoDesde = millis();
    }

    if (!wm.getConfigPortalActive() &&
        millis() - wifiCaidoDesde > 60000) {
      Serial.println("Abriendo portal de configuracion WiFi.");
      wm.startConfigPortal(AP_NOMBRE, AP_CLAVE);
      wifiCaidoDesde = millis();
    }
  }

  if (digitalRead(PIN_BOTON_BOOT) == LOW) {
    if (botonDesde == 0) {
      botonDesde = millis();
    }

    if (millis() - botonDesde > 3000) {
      Serial.println("Borrando configuracion WiFi.");
      wm.resetSettings();
      delay(300);
      ESP.restart();
    }
  } else {
    botonDesde = 0;
  }
}

void enviarPorWifi(float temp, bool tempOk,
                   float nivel, bool nivelOk,
                   float turb, bool turbOk) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi no conectado. No se envio la lectura.");
    return;
  }

  if (!tempOk && !nivelOk && !turbOk) {
    Serial.println("No hay lecturas validas para enviar.");
    return;
  }

  String json = "{\"mac\":\"" + WiFi.macAddress() +
                "\",\"rssi\":" + String(WiFi.RSSI());

  if (tempOk) {
    json += ",\"temperatura\":" + String(temp, 1);
  }

  if (nivelOk) {
    json += ",\"nivel_agua\":" + String(nivel, 1);
  }

  if (turbOk) {
    json += ",\"turbidez\":" + String(turb, 1);
  }

  json += "}";

  WiFiClientSecure cliente;
  cliente.setInsecure();

  HTTPClient http;
  http.setTimeout(10000);

  if (!http.begin(cliente, SERVER_URL)) {
    Serial.println("No se pudo iniciar la conexion con el servidor.");
    return;
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);

  int codigo = http.POST(json);

  if (codigo >= 200 && codigo < 300) {
    Serial.println("Lecturas enviadas correctamente a AquaMonitor.");
  } else if (codigo == 401) {
    Serial.println("ERROR 401: la API KEY no coincide con Vercel.");
  } else if (codigo < 0) {
    Serial.printf("Error de conexion WiFi/HTTPS: %s\n", http.errorToString(codigo).c_str());
  } else {
    Serial.printf("Error del servidor HTTP %d: %s\n", codigo, http.getString().c_str());
  }

  http.end();
}

#endif

// ============================================================
// SETUP
// ============================================================

void setup() {
  Serial.begin(115200);
  sensors.begin();

  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);

  analogReadResolution(12);
  analogSetPinAttenuation(pinTurbidez, ADC_11db);

#if USAR_BLE
  iniciarBle();
#endif

#if USAR_WIFI
  pinMode(PIN_BOTON_BOOT, INPUT_PULLUP);
  conectarWifi();
#endif
}

// ============================================================
// LOOP
// ============================================================

void loop() {
#if USAR_WIFI
  gestionarWifi();
#endif

  if (millis() - ultimaLectura < INTERVALO_LECTURA_MS) {
    return;
  }

  ultimaLectura = millis();

  // 1. Temperatura
  float temperaturaC = 0;
  bool tempOk = leerTemperatura(temperaturaC);

  // 2. Nivel de agua
  float distanciaCm = leerDistanciaCm();
  bool nivelOk = distanciaCm >= 0;
  float nivelPct = 0;

  if (nivelOk) {
    nivelPct = (DIST_SENSOR_FONDO_CM - distanciaCm) /
               (DIST_SENSOR_FONDO_CM - DIST_SENSOR_LLENO_CM) * 100.0;
    nivelPct = constrain(nivelPct, 0.0, 100.0);
  }

  // 3. Turbidez
  int turbRaw = 0;
  float turbNtu = 0;
  bool turbOk = leerTurbidez(turbRaw, turbNtu);

  // 4. Mostrar resultados
  Serial.print("Temp. del agua: ");
  if (tempOk) {
    Serial.print(temperaturaC, 1);
    Serial.print(" °C  |  ");
  } else {
    Serial.print("Sin dato  |  ");
  }

  Serial.print("Nivel de agua: ");
  if (nivelOk) {
    Serial.print(nivelPct, 1);
    Serial.print(" %  |  ");
  } else {
    Serial.print("Sin dato  |  ");
  }

  Serial.print("Turbidez del agua: ");
  if (turbOk) {
    Serial.print(turbNtu, 1);
    Serial.println(" NTU");
  } else {
    Serial.println("Sin dato");
  }

  // 5. Enviar por Bluetooth
#if USAR_BLE
  enviarPorBle(
    temperaturaC, tempOk,
    nivelPct, nivelOk,
    turbNtu, turbOk
  );
#endif

  // 6. Enviar por WiFi
#if USAR_WIFI
  if (WiFi.status() == WL_CONNECTED &&
      millis() - ultimoEnvioWifi >= INTERVALO_ENVIO_WIFI_MS) {
    ultimoEnvioWifi = millis();
    enviarPorWifi(
      temperaturaC, tempOk,
      nivelPct, nivelOk,
      turbNtu, turbOk
    );
  }
#endif
}