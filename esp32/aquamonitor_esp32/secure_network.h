#pragma once
// Network-only extension. Sensor pins, measurements and calibration stay in the .ino.
#include <ArduinoJson.h>
#include <Preferences.h>
#include <esp_random.h>
#include <esp_sntp.h>

WiFiManager wm;
Preferences identidadNvs;
JsonDocument identidad;
const char* AP_NOMBRE = "AquaMonitor-Setup";
const char* AP_CLAVE = AQUAMONITOR_WIFI_PORTAL_PASSWORD;
const char* SERVER_URL = AQUAMONITOR_SERVER_URL;  // existing HTTPS /api/lecturas setting
const char* ROOT_CA_CERT = AQUAMONITOR_ROOT_CA;
const int PIN_BOTON_BOOT = 0;
unsigned long wifiCaidoDesde = 0;
unsigned long botonDesde = 0;
bool wifiEstabaConectado = false;
bool wifiConfigurado = false;
bool identidadLista = false;
bool identidadBloqueada = false;
bool enviosHabilitados = false;
bool vinculado = false;
bool vinculacionLocal = false;
unsigned long inicioVinculacion = 0;
unsigned long siguienteGestion = 0;
unsigned long esperaGestion = 2000;
unsigned long siguienteEnvioSeguro = 0;
unsigned long esperaEnvioSeguro = 2000;
bool botonLargo = false;
String codigoVinculacion;
time_t codigoExpira = 0;
String estadoIdentidad = "Pendiente de conexión segura";

void actualizarEstadoIdentidad(const String& nuevo) {
  if (estadoIdentidad != nuevo) {
    estadoIdentidad = nuevo;
    Serial.println("Estado AquaMonitor: " + nuevo);
  }
}

bool uuidValido(const String& value) {
  if (value.length() != 36) return false;
  for (size_t i = 0; i < value.length(); ++i) {
    bool separator = i == 8 || i == 13 || i == 18 || i == 23;
    char c = value[i];
    if (separator ? c != '-' : !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
  }
  return true;
}

bool credencialValida(const String& value, const char* prefijo) {
  if (value.length() != 67 || !value.startsWith(prefijo)) return false;
  for (size_t i = 3; i < value.length(); ++i) {
    char c = value[i];
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
  }
  return true;
}

bool codigoValido(const String& value) {
  if (value.length() != 12) return false;
  for (size_t i = 0; i < value.length(); ++i) {
    char c = value[i];
    if (!((c >= 'A' && c <= 'Z') || (c >= '2' && c <= '7'))) return false;
  }
  return true;
}

void informarErrorProtocolo(const char* etapa, int code) {
  // Fixed messages only. Never print tokens, request bodies or raw server errors.
  if (code == -1001) { Serial.println("HTTPS pendiente: configuracion incompleta o NTP no confirmado."); return; }
  if (code == -1002) { Serial.println("Respuesta del servidor: JSON o campos no validos; operacion no confirmada."); return; }
  if (code == -1003) { Serial.println("HTTPS: no se pudo preparar la URL y el cliente seguro."); return; }
  if (code < 0) {
    Serial.printf("AquaMonitor %s: fallo local/transporte %d; no es un estado HTTP.\n", etapa, code);
    return;
  }
  Serial.printf("AquaMonitor %s: HTTP %d. ", etapa, code);
  if (code == 401) Serial.println("Credencial individual rechazada. No se soluciona con una API key global.");
  else if (code == 403) Serial.println("Operación no autorizada; revisa vinculación o recuperación en tu cuenta.");
  else if (code == 409) Serial.println("Solicitud vencida, equipo ya vinculado o generación no disponible.");
  else if (code == 503) Serial.println("Servidor no disponible o configuracion del backend pendiente.");
  else if (code == 429) Serial.println("Límite de intentos; se aplicará espera antes de reintentar.");
  else if (code < 0) Serial.println("Fallo de conexión TLS o respuesta JSON no válida; no se desactiva TLS.");
  else Serial.println("El servidor no confirmó la operación; se reintentará con espera.");
}

void diagnosticarConfiguracion() {
  String url(SERVER_URL);
  bool urlOk = url.startsWith("https://") && url.endsWith("/api/lecturas");
  Serial.println("Protocolo: Authorization Bearer; ac_ para configuración y am_ para mediciones.");
  Serial.println(urlOk ? "URL HTTPS: configurada." : "Falta AQUAMONITOR_SERVER_URL HTTPS terminada en /api/lecturas.");
  Serial.println(strlen(ROOT_CA_CERT) ? "CA TLS: configurada; su validez se comprobará al conectar." : "Falta AQUAMONITOR_ROOT_CA; no se iniciará HTTPS sin validar certificados.");
  Serial.println(strlen(AP_CLAVE) >= 8 && strlen(AP_CLAVE) <= 63 ? "Contraseña del portal: longitud válida." : "Falta AQUAMONITOR_WIFI_PORTAL_PASSWORD de 8 a 63 caracteres.");
  Serial.println("BOOT breve: código temporal. BOOT 3 segundos: restablecer solo WiFi.");
}


String secretoAleatorio(const char* prefijo) {
  uint8_t bytes[32];
  esp_fill_random(bytes, sizeof(bytes));  // RF is enabled before this function is used.
  const char* hex = "0123456789abcdef";
  String value(prefijo);
  value.reserve(strlen(prefijo) + 64);
  for (uint8_t byte : bytes) { value += hex[byte >> 4]; value += hex[byte & 15]; }
  memset(bytes, 0, sizeof(bytes));
  return value;
}

String uuidAleatorio() {
  uint8_t bytes[16];
  esp_fill_random(bytes, sizeof(bytes));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  char text[37];
  snprintf(text, sizeof(text), "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
           bytes[0],bytes[1],bytes[2],bytes[3],bytes[4],bytes[5],bytes[6],bytes[7],bytes[8],bytes[9],bytes[10],bytes[11],bytes[12],bytes[13],bytes[14],bytes[15]);
  return String(text);
}

bool guardarIdentidad() {
  String serialized;
  serializeJson(identidad, serialized);
  // One NVS blob: no half-written set of independent credential fields.
  if (!identidadNvs.putString("identity", serialized) || identidadNvs.getString("identity", "") != serialized) {
    identidadLista = false;
    enviosHabilitados = false;
    estadoIdentidad = "Error guardando identidad; envíos detenidos";
    Serial.println(estadoIdentidad);
    return false;
  }
  return true;
}

void iniciarIdentidad() {
  if (!identidadNvs.begin("aquamon-sec", false)) {
    estadoIdentidad = "No se pudo abrir almacenamiento seguro";
    return;
  }
  String saved = identidadNvs.getString("identity", "");
  if (saved.length()) {
    if (deserializeJson(identidad, saved)
        || !credencialValida(identidad["config"].as<String>(), "ac_")
        || !credencialValida(identidad["measurement"].as<String>(), "am_")
        || !uuidValido(identidad["registration_id"].as<String>())
        || !uuidValido(identidad["generation"].as<String>())) {
      estadoIdentidad = "Identidad dañada; requiere revisión local";
      return;  // NEVER silently replace an existing identity.
    }
    identidadLista = true;
  } else {
    identidad["config"] = secretoAleatorio("ac_");
    identidad["measurement"] = secretoAleatorio("am_");
    identidad["registration_id"] = uuidAleatorio();
    identidad["generation"] = uuidAleatorio();
    identidad["public_id"] = "";
    identidadLista = true;
    if (!guardarIdentidad()) return;
    vinculacionLocal = true;  // first physical setup only
    inicioVinculacion = millis();
  }
}

bool configuracionServidorCompleta() {
  String url(SERVER_URL);
  return url.startsWith("https://") && url.endsWith("/api/lecturas") && strlen(ROOT_CA_CERT) > 0;
}

bool relojSincronizado() {
  static bool ntpConfirmado = false;
  if (!ntpConfirmado && sntp_get_sync_status() == SNTP_SYNC_STATUS_COMPLETED) {
    ntpConfirmado = true;
    time_t now = time(nullptr);
    struct tm utc;
    char fecha[32];
    gmtime_r(&now, &utc);
    strftime(fecha, sizeof(fecha), "%Y-%m-%dT%H:%M:%SZ", &utc);
    Serial.printf("Reloj NTP confirmado: epoch=%lld UTC=%s\n", (long long)now, fecha);
  }
  return ntpConfirmado && time(nullptr) >= 1704067200;
}

String urlApi(const char* path) {
  String url(SERVER_URL);
  url.remove(url.length() - String("/api/lecturas").length());
  return url + "/api" + path;
}

// The physical ESP32 exhausted the previous 8 s handshake deadline.
// Separate TCP, TLS and response budgets; certificate checks remain mandatory.
constexpr unsigned long HTTPS_HANDSHAKE_SEGUNDOS = 30;
constexpr int HTTPS_CONEXION_MS = 10000;
constexpr int HTTPS_RESPUESTA_MS = 15000;

// Runs only after a transport failure, at most once per minute. No HTTP requests.
void diagnosticarTransporte() {
  static bool ejecutado = false;
  static unsigned long ultimo = 0;
  if (ejecutado && millis() - ultimo < 60000UL) return;
  ejecutado = true;
  ultimo = millis();
  Serial.printf("Diagnostico WiFi: estado=%d RSSI=%d heap=%u maxAlloc=%u\n",
                (int)WiFi.status(), WiFi.RSSI(), ESP.getFreeHeap(), ESP.getMaxAllocHeap());
  Serial.printf("Diagnostico reloj: epoch=%lld sincronizado=%s\n",
                (long long)time(nullptr), relojSincronizado() ? "si" : "no");
  if (WiFi.status() != WL_CONNECTED) return;
  String host(SERVER_URL);
  host.remove(0, 8);  // https://
  int slash = host.indexOf('/');
  if (slash >= 0) host.remove(slash);
  IPAddress address;
  if (!WiFi.hostByName(host.c_str(), address)) {
    Serial.println("Diagnostico DNS: FALLO");
    return;
  }
  Serial.println("Diagnostico DNS: OK");
  {
    WiFiClient tcp;
    bool connected = tcp.connect(address, 443, 5000);
    tcp.stop();
    Serial.println(connected ? "Diagnostico TCP 443: OK" : "Diagnostico TCP 443: FALLO");
    if (!connected) return;
  }
  diagnosticarMemoria("antes TLS diagnostico");
  WiFiClientSecure tls;
  tls.setCACert(ROOT_CA_CERT);
  tls.setHandshakeTimeout(HTTPS_HANDSHAKE_SEGUNDOS);
  unsigned long inicioTls = millis();
  // Hostname, not IP: preserves SNI and certificate hostname validation.
  if (!tls.connect(host.c_str(), 443, HTTPS_CONEXION_MS)) {
    char detail[192] = {0};
    int error = tls.lastError(detail, sizeof(detail));
    Serial.printf("Diagnostico TLS: FALLO codigo=%d detalle=%s duracion=%lu ms limiteHandshake=%lu s\n",
                  error, detail, millis()-inicioTls, HTTPS_HANDSHAKE_SEGUNDOS);
  } else {
    Serial.printf("Diagnostico TLS: OK; CA y dominio validados; SNI por dominio; duracion=%lu ms\n", millis()-inicioTls);
  }
  tls.stop();
  diagnosticarMemoria("despues detener TLS diagnostico");
}

int peticionSegura(const char* path, const char* method, const String& credential, JsonDocument* input, JsonDocument& output) {
  if (!configuracionServidorCompleta() || !relojSincronizado()) {
    Serial.println("HTTPS no iniciado: falta configuracion o reloj NTP valido.");
    return -1001;
  }
  int code;
  bool falloTransporte;
  diagnosticarMemoria("antes cliente HTTPS");
  {
  WiFiClientSecure cliente;
  diagnosticarMemoria("antes setCACert");
  cliente.setCACert(ROOT_CA_CERT);
  diagnosticarMemoria("despues setCACert");
  cliente.setHandshakeTimeout(HTTPS_HANDSHAKE_SEGUNDOS);
  HTTPClient http;
  if (!http.begin(cliente, urlApi(path))) return -1003;
  http.useHTTP10(true);
  http.setTimeout(HTTPS_RESPUESTA_MS);
  http.setConnectTimeout(HTTPS_CONEXION_MS);
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Accept", "application/json");
  http.addHeader("Authorization", "Bearer " + credential);
  // URL contains only the public host/path; never print headers or bodies.
  Serial.println("HTTPS destino: " + urlApi(path));
  diagnosticarMemoria("antes handshake HTTPS");
  unsigned long inicioPeticion = millis();
  if (strcmp(method, "GET") == 0) {
    code = http.GET();
  } else {
    String payload;
    if (input) serializeJson(*input, payload);
    code = http.POST(payload);
  }
  Serial.printf("HTTPS resultado: codigo=%d duracion=%lu ms limiteHandshake=%lu s\n",
                code, millis()-inicioPeticion, HTTPS_HANDSHAKE_SEGUNDOS);
  if (code > 0) {
    static bool transporteConfirmado = false;
    if (!transporteConfirmado) {
      Serial.println("Internet: DISPONIBLE (Vercel Preview responde)");
      Serial.println("TLS: VALIDADO (CA y dominio)");
      transporteConfirmado = true;
    }
  }
  diagnosticarMemoria("despues peticion HTTPS");
  falloTransporte = code < 0;
  if (falloTransporte) {
    char detail[192] = {0};
    int tlsError = cliente.lastError(detail, sizeof(detail));
    Serial.printf("HTTPClient transporte=%d (%s); TLS=%d detalle=%s\n",
                  code, HTTPClient::errorToString(code).c_str(), tlsError, detail);
  }
  if (code >= 200 && code < 300) {
    if (http.getSize() > 4096 || deserializeJson(output, http.getStream())) code = -1002;
  }
  // Do not print request bodies, response bodies, headers or credentials.
  http.end();
  cliente.stop();
  }  // Both clients are destroyed before any new diagnostic handshake.
  diagnosticarMemoria("despues liberar HTTPS");
  if (falloTransporte) diagnosticarTransporte();
  return code;
}

void activarVinculacionLocal() {
  if (!identidadLista || identidadBloqueada) return;
  vinculacionLocal = true;
  inicioVinculacion = millis();
  codigoVinculacion = "";
  codigoExpira = 0;
  identidad["pair_request"] = uuidAleatorio();
  if (!guardarIdentidad()) return;
  siguienteGestion = 0;
  wm.setConfigPortalTimeout(600);
  if (!wm.getConfigPortalActive()) wm.startConfigPortal(AP_NOMBRE, AP_CLAVE);
  Serial.println("Vinculación local activada por 10 minutos. Portal: /vinculacion, usuario aquamonitor y clave local del portal.");
}

void instalarPortalSeguro() {
  // All portal routes require the AP interface and local authentication.
  // No credentials are exposed through the portal, including diagnostic pages.
  wm.server->addMiddleware([](WebServer& server, Middleware::Callback next) -> bool {
    if (server.client().localIP() != WiFi.softAPIP()) {
      server.send(403, "text/plain", "Accede desde AquaMonitor-Setup");
      return false;
    }
    if (!server.authenticate("aquamonitor", AP_CLAVE)) {
      server.requestAuthentication();
      return false;
    }
    if (server.uri() == "/update" || server.uri() == "/u" || server.uri() == "/updatedone" || server.uri() == "/erase") {
      server.send(403, "text/plain", "Operación deshabilitada");
      return false;
    }
    String origin = server.header("Origin");
    if (origin.length() && origin != "http://" + WiFi.softAPIP().toString()) {
      server.send(403, "text/plain", "Origen no permitido");
      return false;
    }
    server.sendHeader("Cache-Control", "no-store");
    server.sendHeader("X-Content-Type-Options", "nosniff");
    return next();
  });
  const char* headers[] = {"Origin"};
  wm.server->collectHeaders(headers, 1);
  wm.server->on("/vinculacion", HTTP_GET, []() {
    String page = "<!doctype html><html lang='es'><meta charset='utf-8'><meta name='viewport' content='width=device-width'><meta http-equiv='refresh' content='5'><title>AquaMonitor</title><h1>Vincular tu ESP32</h1>";
    if (vinculacionLocal && codigoVinculacion.length() && time(nullptr) < codigoExpira) {
      page += "<p>Código temporal, de un solo uso:</p><h2>" + codigoVinculacion + "</h2><p>Escríbelo en tu cuenta AquaMonitor. Caduca en 10 minutos como máximo.</p>";
    } else {
      page += "<p>" + estadoIdentidad + "</p><p>Pulsa brevemente BOOT para activar una nueva vinculación si el dispositivo está libre.</p>";
    }
    page += "<p>Las credenciales privadas nunca se muestran aquí.</p></html>";
    wm.server->send(200, "text/html; charset=utf-8", page);
  });
}

void avisoPortalAbierto(WiFiManager*) {
  Serial.println("Portal local AquaMonitor-Setup. Usuario: aquamonitor; utiliza la clave privada del portal.");
}

void conectarWifi() {
  diagnosticarConfiguracion();
  if (strlen(AP_CLAVE) < 8 || strlen(AP_CLAVE) > 63) {
    Serial.println("Configura una clave local de portal de 8 a 63 caracteres.");
    return;
  }
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  iniciarIdentidad();
  wm.setDebugOutput(false);
  wm.setConnectTimeout(20);
  wm.setConfigPortalTimeout(180);
  wm.setConfigPortalBlocking(false);
  wm.setAPCallback(avisoPortalAbierto);
  wm.setWebServerCallback(instalarPortalSeguro);
  wm.setCustomMenuHTML("<p><a href='/vinculacion'>Consultar código de vinculación</a></p>");
  wifiConfigurado = true;
  wm.autoConnect(AP_NOMBRE, AP_CLAVE);
}

void gestionarWifi() {
  if (!wifiConfigurado) return;
  wm.process();
  bool connected = WiFi.status() == WL_CONNECTED;
  if (connected && !wifiEstabaConectado) {
    diagnosticarMemoria("WiFi conectado");
    Serial.println("WiFi: CONECTADO (red de 2.4 GHz; el AP local no es internet)");
    Serial.print("IP local: "); Serial.println(WiFi.localIP());
    Serial.print("DNS configurado: "); Serial.println(WiFi.dnsIP());
    Serial.println("WiFi conectado; sincronizando reloj para TLS.");
    configTime(0, 0, "pool.ntp.org", "time.cloudflare.com");
    siguienteGestion = 0;
  }
  if (!connected && wifiEstabaConectado) {
    Serial.println("WiFi: DESCONECTADO; reconexion automatica activa");
    Serial.println("Internet: NO CONFIRMADO; envios pausados");
  }
  wifiEstabaConectado = connected;
  if (connected) {
    wifiCaidoDesde = 0;
  } else {
    enviosHabilitados = false;
    if (!wifiCaidoDesde) wifiCaidoDesde = millis();
    if (!wm.getConfigPortalActive() && millis()-wifiCaidoDesde > 60000) {
      wm.startConfigPortal(AP_NOMBRE, AP_CLAVE);
      wifiCaidoDesde = millis();
    }
  }
  if (digitalRead(PIN_BOTON_BOOT) == LOW) {
    if (!botonDesde) botonDesde = millis();
    if (!botonLargo && millis()-botonDesde > 3000) {
      botonLargo = true;
      wm.resetSettings();  // WiFi only. Never erase aquamon-sec identity.
      ESP.restart();
    }
  } else if (botonDesde) {
    if (!botonLargo && millis()-botonDesde > 50) activarVinculacionLocal();
    botonDesde = 0;
    botonLargo = false;
  }
  if (vinculacionLocal && millis()-inicioVinculacion >= 600000) {
    vinculacionLocal = false;
    codigoVinculacion = "";
    codigoExpira = 0;
    if (connected && wm.getConfigPortalActive()) wm.stopConfigPortal();
  }
}

void reintentarGestion() {
  esperaGestion = min(esperaGestion * 2, 60000UL);
  siguienteGestion = millis() + esperaGestion + (esp_random() % 1000);
}

void gestionarIdentidad() {
  if (!identidadLista || identidadBloqueada || WiFi.status()!=WL_CONNECTED) return;
  if (siguienteGestion && (int32_t)(millis()-siguienteGestion)<0) return;
  if (!configuracionServidorCompleta() || !relojSincronizado()) {
    actualizarEstadoIdentidad("Pendiente de URL HTTPS, CA o reloj NTP");
    reintentarGestion();
    return;
  }
  JsonDocument input, output;
  String config = identidad["config"].as<String>();
  int code;
  if (!identidad["public_id"].as<String>().length()) {
    input["registration_id"] = identidad["registration_id"];
    input["generation"] = identidad["generation"];
    input["measurement_token"] = identidad["measurement"];
    input["mac"] = WiFi.macAddress();
    actualizarEstadoIdentidad("Registrando identidad individual por HTTPS");
    code = peticionSegura("/equipos/registro", "POST", config, &input, output);
    if (code!=200 && code!=201) { informarErrorProtocolo("registro", code); reintentarGestion(); return; }
    if (!uuidValido(output["public_id"].as<String>())) {
      informarErrorProtocolo("registro/respuesta", -1002); reintentarGestion(); return;
    }
    identidad["public_id"] = output["public_id"];
    if (!guardarIdentidad()) return;
    Serial.println("Registro: EXITOSO; identidad individual guardada");
    // A previously interrupted first registration must also open its physical pairing window.
    vinculacionLocal = true;
    inicioVinculacion = millis();
    output.clear();
  }
  code = peticionSegura("/equipos/estado", "GET", config, nullptr, output);
  if (code == 401) {
    identidadBloqueada = true;
    enviosHabilitados = false;
    actualizarEstadoIdentidad("Credencial de configuración rechazada; requiere revisión local de la identidad");
    informarErrorProtocolo("consulta de estado", code);
    return;
  }
  if (code != 200) { informarErrorProtocolo("consulta de estado", code); reintentarGestion(); return; }
  if (!output["linked"].is<bool>() || !output["measurement_enabled"].is<bool>() || !output["recovery_authorized"].is<bool>()) {
    enviosHabilitados = false;
    informarErrorProtocolo("estado/respuesta", -1002); reintentarGestion(); return;
  }
  bool estabaVinculado = vinculado;
  bool estabaHabilitado = enviosHabilitados;
  vinculado = output["linked"] | false;
  enviosHabilitados = output["measurement_enabled"] | false;
  bool recover = output["recovery_authorized"] | false;
  if (vinculado) {
    if (!estabaVinculado) Serial.println("Dispositivo: VINCULADO");
    if (enviosHabilitados && !estabaHabilitado) {
      Serial.println("Autenticacion: CORRECTA");
      Serial.println("Envio de sensores: ACTIVO");
    }
    codigoVinculacion = "";
    codigoExpira = 0;
    if (recover && !identidad["pending_token"].is<String>()) {
      identidad["pending_token"] = secretoAleatorio("am_");
      identidad["pending_generation"] = uuidAleatorio();
      if (!guardarIdentidad()) return;  // durable BEFORE network request
    }
    if (identidad["pending_token"].is<String>()) {
      enviosHabilitados = false;
      input.clear(); output.clear();
      input["generation"] = identidad["pending_generation"];
      input["measurement_token"] = identidad["pending_token"];
      code = peticionSegura("/equipos/credenciales/medicion", "POST", config, &input, output);
      if (code != 200) {
        informarErrorProtocolo("recuperación", code);
        // Conflict means this generation was revoked or belongs to a previous assignment.
        if (code == 409) {
          identidad.remove("pending_token"); identidad.remove("pending_generation");
          guardarIdentidad();
        }
        reintentarGestion(); return;
      }
      identidad["measurement"] = identidad["pending_token"];
      identidad["generation"] = identidad["pending_generation"];
      identidad.remove("pending_token"); identidad.remove("pending_generation");
      if (!guardarIdentidad()) return;
      enviosHabilitados = true;
    }
    actualizarEstadoIdentidad(enviosHabilitados ? "Equipo vinculado; envíos con credencial individual habilitados" : "Envíos revocados; autoriza recuperación en tu cuenta");
  } else {
    enviosHabilitados = false;
    actualizarEstadoIdentidad("Equipo sin vincular; activa el código con BOOT y añádelo desde AquaMonitor");
    if (codigoVinculacion.length() && codigoExpira <= time(nullptr)) {
      codigoVinculacion = "";
      codigoExpira = 0;
      identidad.remove("pair_request");
      if (!guardarIdentidad()) return;
      Serial.println("Codigo temporal: VENCIDO; solo se aceptara uno nuevo del backend");
    }
    if (vinculacionLocal && !codigoVinculacion.length()) {
      if (!identidad["pair_request"].is<String>()) {
        identidad["pair_request"] = uuidAleatorio();
        if (!guardarIdentidad()) return;
      }
      input.clear(); output.clear();
      input["request_id"] = identidad["pair_request"];
      code = peticionSegura("/equipos/vinculacion", "POST", config, &input, output);
      if (code == 200) {
        String receivedCode = output["code"].as<String>();
        time_t expires = output["expires_at"].as<time_t>();
        if (!codigoValido(receivedCode) || expires <= time(nullptr)) {
          informarErrorProtocolo("vinculación/respuesta", -1002); reintentarGestion(); return;
        }
        codigoVinculacion = receivedCode;
        codigoExpira = expires;
        Serial.println("Código temporal de vinculación: " + codigoVinculacion);
        struct tm utc;
        char fecha[32];
        gmtime_r(&codigoExpira, &utc);
        strftime(fecha, sizeof(fecha), "%Y-%m-%dT%H:%M:%SZ", &utc);
        Serial.printf("Vence: %s (en %lld segundos)\n", fecha, (long long)(codigoExpira-time(nullptr)));
        Serial.println("Estado: ESPERANDO VINCULACION");
        Serial.println("También disponible en el portal local /vinculacion. Código de un solo uso, máximo 10 minutos.");
        if (!wm.getConfigPortalActive()) { wm.setConfigPortalTimeout(600); wm.startConfigPortal(AP_NOMBRE, AP_CLAVE); }
      } else {
        informarErrorProtocolo("código de vinculación", code);
        if (code == 409) { identidad.remove("pair_request"); guardarIdentidad(); }
        reintentarGestion(); return;
      }
    }
  }
  esperaGestion = 2000;
  siguienteGestion = millis() + 10000;
}

void enviarPorWifi(float temp, bool tempOk, float nivel, bool nivelOk, float turbidez, bool turbidezOk, float distanciaCm) {
  if (!identidadLista || !enviosHabilitados || identidadBloqueada || (!tempOk && !nivelOk && !turbidezOk)) return;
  if (siguienteEnvioSeguro && (int32_t)(millis()-siguienteEnvioSeguro)<0) return;
  JsonDocument input, output;
  input["rssi"] = WiFi.RSSI();
  if (tempOk) input["temperatura"] = serialized(String(temp,1));
  input["temperatura_estado"] = AquaMonitorTemperatura::texto(estadoTemperatura);
  if (estadoTemperatura == AquaMonitorTemperatura::Estado::Sospechosa) input["temperatura_observada"] = serialized(String(temp,2));
  if (nivelOk) input["nivel_agua"] = serialized(String(nivel,1));
  if (AquaMonitorNivel::distanciaValida(distanciaCm)) input["distancia_cm"] = serialized(String(distanciaCm,2));
  input["nivel_calibracion"] = "provisional-7.8-2.0";
  if (turbidezOk) input["turbidez"] = serialized(String(turbidez,1));
  int code = peticionSegura("/lecturas", "POST", identidad["measurement"].as<String>(), &input, output);
  if (code == 200) {
    esperaEnvioSeguro = 2000;
    siguienteEnvioSeguro = 0;
    static bool avisoTrazabilidad = false;
    if (!avisoTrazabilidad && output["trazabilidad_guardada"].is<bool>() && !output["trazabilidad_guardada"].as<bool>()) {
      Serial.println("Medicion util guardada; distancia y diagnosticos no persistidos sin migracion opcional 003.");
      avisoTrazabilidad = true;
    }
    Serial.println("Envio de sensores: CONFIRMADO por Vercel");
    Serial.println("Historial: medicion guardada por el backend");
  } else {
    esperaEnvioSeguro = min(esperaEnvioSeguro * 2, 60000UL);
    siguienteEnvioSeguro = millis() + esperaEnvioSeguro + (esp_random() % 1000);
    informarErrorProtocolo("mediciones", code);
    if (code == 401 || code == 403) { enviosHabilitados = false; siguienteGestion = 0; }
  }
}
