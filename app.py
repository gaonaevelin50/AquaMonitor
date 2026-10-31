"""
AquaMonitor - backend (Flask + PostgreSQL), listo para Vercel

Qué hace:
  - Recibe por WiFi las lecturas que envía el ESP32 (POST /api/lecturas).
  - Guarda usuarios, dispositivos y lecturas en una base de datos PostgreSQL en la nube.
  - El dashboard (carpeta public/) lo sirve el CDN de Vercel y le entrega los datos reales.

Variables de entorno (se configuran en Vercel > Settings > Environment Variables):
  DATABASE_URL         conexión a PostgreSQL (la crea Neon/Vercel Postgres)
  SECRET_KEY           clave larga y secreta para firmar las sesiones
  AQUAMONITOR_API_KEY  la misma clave que pones en el .ino del ESP32
"""
import hmac
import os
import re
import socket
import time
from functools import wraps

import psycopg
from psycopg.rows import dict_row
from flask import Flask, g, jsonify, request, send_from_directory
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

# =========================
# CONFIGURACIÓN
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUERTO = int(os.environ.get("PORT", 5000))
EN_VERCEL = bool(os.environ.get("VERCEL"))

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
if not DATABASE_URL:
    raise RuntimeError("Falta la variable de entorno DATABASE_URL (conexión a PostgreSQL).")

# Clave que debe enviar el ESP32 en la cabecera X-API-Key.
# CÁMBIALA (aquí o con la variable de entorno AQUAMONITOR_API_KEY)
# y pon la misma en el código del ESP32.
API_KEY_DISPOSITIVOS = os.environ.get("AQUAMONITOR_API_KEY", "AQUAMONITOR_API_KEY_PLACEHOLDER")

SEGUNDOS_SIN_SENAL = 30          # sin datos por este tiempo = "Sin señal"
SEGUNDOS_PENDIENTE = 120         # un dispositivo nuevo se ofrece para vincular por este tiempo
TOKEN_HORAS = 24                 # duración de la sesión
MAX_LECTURAS_POR_DISPOSITIVO = 5000
MAX_INTENTOS_LOGIN = 5           # intentos fallidos por IP antes de bloquear 60 s

# Rangos físicos posibles de cada sensor (fuera de esto la lectura se rechaza)
SENSORES = {
    "temperatura": {"nombre": "Temperatura", "unidad": "°C", "min": 0, "max": 50},
    "nivel_agua": {"nombre": "Nivel de Agua", "unidad": "%", "min": 0, "max": 100},
    "turbidez": {"nombre": "Turbidez", "unidad": "NTU", "min": 0, "max": 3000},
    "ph": {"nombre": "pH", "unidad": "pH", "min": 0, "max": 14},
}
NOMBRE_A_CLAVE = {cfg["nombre"]: clave for clave, cfg in SENSORES.items()}

# En Vercel el panel (carpeta public/) lo sirve el CDN; esta carpeta solo se usa al correr en local.
app = Flask(__name__, static_folder="public", static_url_path="")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0   # el navegador siempre pide la versión nueva


def cargar_secret():
    """Clave secreta de las sesiones: variable de entorno SECRET_KEY (obligatoria en Vercel)."""
    clave = os.environ.get("SECRET_KEY", "")
    if clave:
        return clave
    if EN_VERCEL:
        raise RuntimeError("Falta la variable de entorno SECRET_KEY.")
    return "clave-solo-para-desarrollo-local"


serializador = URLSafeTimedSerializer(cargar_secret(), salt="aquamonitor-token")


def ip_cliente():
    """IP real de quien hace la petición (detrás del proxy de Vercel)."""
    reenviada = request.headers.get("X-Forwarded-For", "")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.remote_addr or "desconocida"


# =========================
# BASE DE DATOS (PostgreSQL)
# =========================
class Db:
    """Envoltura mínima para usar execute(...).fetchone() con marcadores ? como antes."""

    def __init__(self, conexion):
        self.conexion = conexion

    def execute(self, sql, params=()):
        return self.conexion.execute(sql.replace("?", "%s"), params)

    def commit(self):
        self.conexion.commit()

    def close(self):
        self.conexion.close()


def get_db():
    if "db" not in g:
        g.db = Db(psycopg.connect(DATABASE_URL, row_factory=dict_row))
    return g.db


@app.teardown_appcontext
def cerrar_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id BIGSERIAL PRIMARY KEY,
    usuario TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    creado_en BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS dispositivos (
    id BIGSERIAL PRIMARY KEY,
    mac TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    owner_id BIGINT REFERENCES usuarios(id),
    ip TEXT,
    rssi INTEGER,
    primera_conexion BIGINT NOT NULL,
    ultima_conexion BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS lecturas (
    id BIGSERIAL PRIMARY KEY,
    device_id BIGINT NOT NULL REFERENCES dispositivos(id) ON DELETE CASCADE,
    ts BIGINT NOT NULL,
    temperatura DOUBLE PRECISION,
    nivel_agua DOUBLE PRECISION,
    turbidez DOUBLE PRECISION,
    ph DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_lecturas_dev_ts ON lecturas(device_id, ts);
CREATE TABLE IF NOT EXISTS intentos_login (
    ip TEXT PRIMARY KEY,
    cantidad INTEGER NOT NULL,
    desde BIGINT NOT NULL
);
"""

_tablas_listas = False


@app.before_request
def preparar_tablas():
    """Crea las tablas la primera vez que arranca el servidor (no hace nada si ya existen)."""
    global _tablas_listas
    if _tablas_listas:
        return
    with psycopg.connect(DATABASE_URL) as con:
        con.execute("SELECT pg_advisory_xact_lock(727001)")   # evita carreras entre instancias
        con.execute(ESQUEMA)
    _tablas_listas = True


# =========================
# UTILIDADES
# =========================
def error(mensaje, codigo):
    return jsonify(detail=mensaje), codigo


def evaluar(clave, v):
    """Devuelve (estado, clase_css) según los mismos umbrales del dashboard."""
    if clave == "temperatura":
        if v < 16:
            return "Bajo", "tag-red"
        return ("Normal", "tag-green") if v <= 26 else ("Alto", "tag-red")
    if clave == "nivel_agua":
        if v < 45:
            return "Bajo", "tag-red"
        return ("Normal", "tag-green") if v <= 85 else ("Alto", "tag-red")
    if clave == "turbidez":
        return ("Normal", "tag-green") if v <= 30 else ("Alta", "tag-red")
    if clave == "ph":
        if v < 6.5:
            return "Bajo", "tag-red"
        return ("Normal", "tag-green") if v <= 8.0 else ("Alto", "tag-red")
    return "Normal", "tag-green"


def etiqueta_senal(rssi):
    if rssi is None:
        return "Desconocida"
    if rssi >= -55:
        return "Excelente"
    if rssi >= -67:
        return "Buena"
    if rssi >= -80:
        return "Regular"
    return "Débil"


def dispositivo_json(fila, ahora):
    return {
        "id": fila["id"],
        "nombre": fila["nombre"],
        "mac": fila["mac"],
        "ip": fila["ip"],
        "rssi": fila["rssi"],
        "senal": etiqueta_senal(fila["rssi"]),
        "primera": fila["primera_conexion"],
        "ultima": fila["ultima_conexion"],
        "en_linea": ahora - fila["ultima_conexion"] <= SEGUNDOS_SIN_SENAL,
    }


def requiere_login(f):
    @wraps(f)
    def envoltura(*args, **kwargs):
        cabecera = request.headers.get("Authorization", "")
        if not cabecera.startswith("Bearer "):
            return error("No has iniciado sesión.", 401)
        try:
            datos = serializador.loads(cabecera[7:], max_age=TOKEN_HORAS * 3600)
        except SignatureExpired:
            return error("Tu sesión expiró. Inicia sesión de nuevo.", 401)
        except BadSignature:
            return error("Sesión inválida. Inicia sesión de nuevo.", 401)
        fila = get_db().execute(
            "SELECT id, usuario FROM usuarios WHERE id = ?", (datos.get("uid"),)
        ).fetchone()
        if fila is None:
            return error("La cuenta ya no existe.", 401)
        g.user = fila
        return f(*args, **kwargs)

    return envoltura


def dispositivo_del_usuario(device_id):
    if device_id is None:
        return None
    return get_db().execute(
        "SELECT * FROM dispositivos WHERE id = ? AND owner_id = ?",
        (device_id, g.user["id"]),
    ).fetchone()


# =========================
# AUTENTICACIÓN
# =========================
@app.post("/api/registro")
def registro():
    datos = request.get_json(silent=True) or {}
    usuario = str(datos.get("usuario", "")).strip()
    password = str(datos.get("password", ""))

    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", usuario):
        return error("El usuario debe tener 3 a 30 caracteres (letras, números, _ . -).", 400)
    if len(password) < 4:
        return error("La contraseña debe tener al menos 4 caracteres.", 400)

    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO usuarios (usuario, password_hash, creado_en) VALUES (?, ?, ?) RETURNING id",
            (usuario, generate_password_hash(password), int(time.time())),
        )
        nuevo_id = cur.fetchone()["id"]
        db.commit()
    except psycopg.errors.UniqueViolation:
        db.conexion.rollback()
        return error("El usuario ya existe.", 409)

    token = serializador.dumps({"uid": nuevo_id})
    return jsonify(token=token, usuario=usuario), 201


@app.post("/api/login")
def login():
    ip = ip_cliente()
    ahora = int(time.time())
    db = get_db()
    previo = db.execute("SELECT cantidad, desde FROM intentos_login WHERE ip = ?", (ip,)).fetchone()
    cantidad, desde = (previo["cantidad"], previo["desde"]) if previo else (0, ahora)
    if ahora - desde > 60:
        cantidad, desde = 0, ahora
    if cantidad >= MAX_INTENTOS_LOGIN:
        return error("Demasiados intentos. Espera un minuto.", 429)

    datos = request.get_json(silent=True) or {}
    usuario = str(datos.get("usuario", "")).strip()
    password = str(datos.get("password", ""))

    fila = db.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    if fila is None or not check_password_hash(fila["password_hash"], password):
        db.execute(
            "INSERT INTO intentos_login (ip, cantidad, desde) VALUES (?, ?, ?) "
            "ON CONFLICT (ip) DO UPDATE SET cantidad = EXCLUDED.cantidad, desde = EXCLUDED.desde",
            (ip, cantidad + 1, desde),
        )
        db.commit()
        return error("Usuario o contraseña incorrectos.", 401)

    db.execute("DELETE FROM intentos_login WHERE ip = ?", (ip,))
    db.commit()
    token = serializador.dumps({"uid": fila["id"]})
    return jsonify(token=token, usuario=fila["usuario"])


@app.get("/api/me")
@requiere_login
def me():
    return jsonify(usuario=g.user["usuario"])


# =========================
# ESP32 -> SERVIDOR (por WiFi)
# =========================
@app.post("/api/lecturas")
def recibir_lectura():
    """El ESP32 llama aquí cada 5 s con la cabecera X-API-Key."""
    clave = request.headers.get("X-API-Key", "")
    if not hmac.compare_digest(clave.encode(), API_KEY_DISPOSITIVOS.encode()):
        return error("API key inválida.", 401)

    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return error("El cuerpo debe ser un JSON.", 400)

    mac = str(datos.get("mac", "")).upper().replace("-", ":")
    if not re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", mac):
        return error("Falta 'mac' o no es válida (formato AA:BB:CC:DD:EE:FF).", 400)

    valores = {}
    for clave_sensor, cfg in SENSORES.items():
        v = datos.get(clave_sensor)
        if v is None:                     # sensor no instalado o con falla
            valores[clave_sensor] = None
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return error(f"'{clave_sensor}' debe ser un número.", 400)
        if not (cfg["min"] <= v <= cfg["max"]):
            return error(
                f"'{clave_sensor}' fuera de rango ({cfg['min']} a {cfg['max']} {cfg['unidad']}).", 422
            )
        valores[clave_sensor] = float(v)

    if all(v is None for v in valores.values()):
        return error("La lectura no trae ningún valor.", 400)

    rssi = datos.get("rssi")
    rssi = int(rssi) if isinstance(rssi, (int, float)) and not isinstance(rssi, bool) else None

    db = get_db()
    ahora = int(time.time())
    disp = db.execute("SELECT id FROM dispositivos WHERE mac = ?", (mac,)).fetchone()
    if disp is None:
        cur = db.execute(
            "INSERT INTO dispositivos (mac, nombre, ip, rssi, primera_conexion, ultima_conexion)"
            " VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (mac, "ESP32-" + mac[-5:].replace(":", ""), ip_cliente(), rssi, ahora, ahora),
        )
        device_id = cur.fetchone()["id"]
    else:
        device_id = disp["id"]
        db.execute(
            "UPDATE dispositivos SET ip = ?, rssi = ?, ultima_conexion = ? WHERE id = ?",
            (ip_cliente(), rssi, ahora, device_id),
        )

    db.execute(
        "INSERT INTO lecturas (device_id, ts, temperatura, nivel_agua, turbidez, ph)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            device_id, ahora, valores["temperatura"], valores["nivel_agua"],
            valores["turbidez"], valores["ph"],
        ),
    )
    # Mantener la base de datos liviana: solo las últimas N lecturas por dispositivo
    db.execute(
        "DELETE FROM lecturas WHERE device_id = ? AND id NOT IN "
        "(SELECT id FROM lecturas WHERE device_id = ? ORDER BY id DESC LIMIT ?)",
        (device_id, device_id, MAX_LECTURAS_POR_DISPOSITIVO),
    )
    db.commit()
    return jsonify(ok=True, intervalo_s=5)


# =========================
# DISPOSITIVOS (dashboard)
# =========================
@app.get("/api/dispositivos")
@requiere_login
def listar_dispositivos():
    ahora = int(time.time())
    filas = get_db().execute(
        "SELECT * FROM dispositivos WHERE owner_id = ? ORDER BY id", (g.user["id"],)
    ).fetchall()
    return jsonify(dispositivos=[dispositivo_json(f, ahora) for f in filas])


@app.get("/api/dispositivos/pendientes")
@requiere_login
def dispositivos_pendientes():
    """ESP32 que están enviando datos por WiFi pero todavía no tienen dueño."""
    ahora = int(time.time())
    filas = get_db().execute(
        "SELECT * FROM dispositivos WHERE owner_id IS NULL AND ultima_conexion >= ? "
        "ORDER BY ultima_conexion DESC",
        (ahora - SEGUNDOS_PENDIENTE,),
    ).fetchall()
    return jsonify(dispositivos=[dispositivo_json(f, ahora) for f in filas])


@app.post("/api/dispositivos/vincular")
@requiere_login
def vincular_dispositivo():
    datos = request.get_json(silent=True) or {}
    mac = str(datos.get("mac", "")).upper()
    nombre = str(datos.get("nombre", "")).strip()[:40]

    db = get_db()
    fila = db.execute("SELECT * FROM dispositivos WHERE mac = ?", (mac,)).fetchone()
    if fila is None:
        return error("No se encontró ese dispositivo.", 404)
    if fila["owner_id"] is not None:
        return error("Ese dispositivo ya está vinculado a una cuenta.", 409)

    db.execute(
        "UPDATE dispositivos SET owner_id = ?, nombre = ? WHERE id = ?",
        (g.user["id"], nombre or fila["nombre"], fila["id"]),
    )
    db.commit()
    nuevo = db.execute("SELECT * FROM dispositivos WHERE id = ?", (fila["id"],)).fetchone()
    return jsonify(dispositivo=dispositivo_json(nuevo, int(time.time()))), 201


@app.delete("/api/dispositivos/<int:device_id>")
@requiere_login
def desvincular_dispositivo(device_id):
    if dispositivo_del_usuario(device_id) is None:
        return error("Dispositivo no encontrado.", 404)
    db = get_db()
    db.execute("DELETE FROM lecturas WHERE device_id = ?", (device_id,))
    db.execute("UPDATE dispositivos SET owner_id = NULL WHERE id = ?", (device_id,))
    db.commit()
    return jsonify(ok=True)


# =========================
# LECTURAS (dashboard)
# =========================
@app.get("/api/lecturas/ultima")
@requiere_login
def ultima_lectura():
    disp = dispositivo_del_usuario(request.args.get("device_id", type=int))
    if disp is None:
        return error("Dispositivo no encontrado.", 404)

    fila = get_db().execute(
        "SELECT * FROM lecturas WHERE device_id = ? ORDER BY id DESC LIMIT 1", (disp["id"],)
    ).fetchone()
    if fila is None:
        return jsonify(sin_datos=True)

    ahora = int(time.time())
    return jsonify(
        sin_datos=False,
        ts=fila["ts"],
        en_linea=ahora - disp["ultima_conexion"] <= SEGUNDOS_SIN_SENAL,
        temperatura=fila["temperatura"],
        nivel_agua=fila["nivel_agua"],
        turbidez=fila["turbidez"],
        ph=fila["ph"],
    )


@app.get("/api/lecturas")
@requiere_login
def historico():
    """Histórico en filas: una por sensor (Fecha, Sensor, Valor, Estado)."""
    disp = dispositivo_del_usuario(request.args.get("device_id", type=int))
    if disp is None:
        return error("Dispositivo no encontrado.", 404)

    filtro = NOMBRE_A_CLAVE.get(request.args.get("sensor", "Todos"))   # None = todos
    claves = [filtro] if filtro else list(SENSORES)
    limite = 100 if filtro else 20

    filas = get_db().execute(
        "SELECT * FROM lecturas WHERE device_id = ? ORDER BY id DESC LIMIT ?",
        (disp["id"], limite),
    ).fetchall()

    registros = []
    for fila in filas:
        for clave in claves:
            v = fila[clave]
            if v is None:
                continue
            estado, clase = evaluar(clave, v)
            registros.append(
                {
                    "ts": fila["ts"],
                    "sensor": SENSORES[clave]["nombre"],
                    "valor": f"{v:.1f} {SENSORES[clave]['unidad']}",
                    "estado": estado,
                    "clase": clase,
                }
            )
    return jsonify(registros=registros)


# =========================
# PÁGINA PRINCIPAL
# =========================
@app.get("/")
def inicio():
    # En Vercel "/" lo atiende el CDN con public/index.html; esto se usa solo en local.
    return send_from_directory(os.path.join(BASE_DIR, "public"), "index.html")


def ip_local():
    """IP de este computador en la red WiFi (para abrir el dashboard desde el celular)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))   # no envía datos, solo averigua qué interfaz usaría
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    ip = ip_local()
    print("\n  AquaMonitor está corriendo")
    print(f"  En este computador:  http://localhost:{PUERTO}")
    print(f"  Desde el celular:    http://{ip}:{PUERTO}   (misma red WiFi)")
    print(f"  El ESP32 debe enviar a:  http://{ip}:{PUERTO}/api/lecturas  (en local; en Vercel usa https://tu-proyecto.vercel.app/api/lecturas)\n")
    if API_KEY_DISPOSITIVOS == "AQUAMONITOR_API_KEY_PLACEHOLDER":
        print("  AVISO: estás usando la API key por defecto. Cámbiala en app.py\n")
    app.run(host="0.0.0.0", port=PUERTO, debug=False, threaded=True)
