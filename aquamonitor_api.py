"""Secure user/device API. Every mutation uses PostgreSQL transactions, no process-local state."""
import base64
import hashlib
import hmac
import math
import re
import secrets
import time
import uuid
from functools import wraps
from temperature_quality import classify_temperature
from level_quality import level_status

from flask import Blueprint, abort, current_app, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

api = Blueprint("api", __name__, url_prefix="/api")
COOKIE = "aquamonitor_session"
SENSORS = {
    "temperatura": ("Temperatura", "°C", -50, 100),
    "nivel_agua": ("Nivel de Agua", "%", 0, 100),
    "turbidez": ("Turbidez", "NTU", 0, 3000),
}
DUMMY_HASH = generate_password_hash("invalid-account-timing-placeholder")


def db():
    return current_app.extensions["aquamonitor_get_db"]()


def now():
    return int(time.time())


def fail(message, code=400):
    response = jsonify(detail=message)
    response.status_code = code
    abort(response)


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("El cuerpo debe ser un objeto JSON.")
    return data


def string(data, key, minimum=1, maximum=128):
    value = data.get(key)
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        fail(f"Campo '{key}' no válido.")
    return value


def uuid_value(value):
    try:
        result = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        fail("Identificador no válido.")
    if result != value:
        fail("Identificador no válido.")
    return result


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def device_token(value, purpose):
    prefix = "ac_" if purpose == "config" else "am_"
    if not isinstance(value, str) or not re.fullmatch(prefix + r"[0-9a-f]{64}", value):
        fail("Credencial de dispositivo no válida.", 401)
    return digest(value)


def bearer(purpose):
    header = request.headers.get("Authorization", "")
    return device_token(header[7:] if header.startswith("Bearer ") else "", purpose)


def client_ip():
    # Only trust the deployment-managed header in Vercel; ignore user X-Forwarded-For locally.
    import os
    value = request.headers.get("x-forwarded-for", "") if os.environ.get("VERCEL") else ""
    return (value.split(",")[0].strip() or request.remote_addr or "unknown")[:128]


def limit(scope, identity, maximum, seconds):
    # Fixed-window counter increment is atomic and committed even if validation later fails.
    key = digest(scope + ":" + str(identity))
    window = now() // seconds
    row = db().execute("""INSERT INTO limites_seguridad(clave,ventana,cantidad) VALUES(%s,%s,1)
        ON CONFLICT(clave) DO UPDATE SET ventana=EXCLUDED.ventana,
        cantidad=CASE WHEN limites_seguridad.ventana=EXCLUDED.ventana
        THEN limites_seguridad.cantidad+1 ELSE 1 END RETURNING cantidad""", (key, window)).fetchone()
    db().commit()
    if row["cantidad"] > maximum:
        fail("Demasiados intentos. Espera antes de volver a intentarlo.", 429)


def csrf_for(token):
    return hmac.new(current_app.config["SECRET_KEY"].encode(), ("csrf:" + token).encode(), hashlib.sha256).hexdigest()


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        token = request.cookies.get(COOKIE, "")
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            fail("Inicia sesión.", 401)
        row = db().execute("""SELECT u.id,u.usuario FROM sesiones_usuario s JOIN usuarios u ON u.id=s.usuario_id
            WHERE s.token_hash=%s AND s.revocado_en IS NULL AND s.expira_en>%s""", (digest(token), now())).fetchone()
        if row is None:
            fail("La sesión expiró o fue cerrada.", 401)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), csrf_for(token)):
                fail("Verificación de sesión no válida. Recarga la página.", 403)
        g.user = row
        return fn(*args, **kwargs)
    return wrapped


@api.before_request
def same_origin_writes():
    if request.path.startswith("/api/equipos/") or (request.path == "/api/lecturas" and request.method == "POST"):
        limit("device-api-ip", client_ip(), 300, 60)
    if request.method in {"POST", "DELETE", "PATCH", "PUT"}:
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            fail("Origen no permitido.", 403)
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            fail("Origen no permitido.", 403)


def start_session(user_id, username):
    token = secrets.token_hex(32)
    ts = now()
    db().execute("INSERT INTO sesiones_usuario(token_hash,usuario_id,creado_en,expira_en) VALUES(%s,%s,%s,%s)",
                 (digest(token), user_id, ts, ts+86400))
    db().commit()
    response = jsonify(usuario=username, csrf_token=csrf_for(token))
    response.set_cookie(COOKIE, token, max_age=86400, secure=current_app.config["SESSION_COOKIE_SECURE"],
                        httponly=True, samesite="Strict", path="/")
    return response


def account_fields(data, registration=False):
    username = string(data, "usuario", 3, 30).strip()
    password = string(data, "password", 5 if registration else 1, 128)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", username):
        fail("Usuario no válido: utiliza de 3 a 30 letras, números, punto, guion o guion bajo.")
    return username, password


@api.post("/registro")
def register_user():
    limit("register-ip", client_ip(), 10, 3600)
    username, password = account_fields(body(), True)
    import psycopg
    try:
        row = db().execute("INSERT INTO usuarios(usuario,password_hash,creado_en) VALUES(%s,%s,%s) RETURNING id",
                           (username, generate_password_hash(password), now())).fetchone()
        response = start_session(row["id"], username)
        response.status_code = 201
        return response
    except psycopg.errors.UniqueViolation:
        db().rollback()
        fail("El usuario ya existe.", 409)


@api.post("/login")
def login():
    limit("login-ip", client_ip(), 10, 60)
    username, password = account_fields(body())
    limit("login-account", username.lower(), 10, 60)
    row = db().execute("SELECT * FROM usuarios WHERE usuario=%s", (username,)).fetchone()
    valid = check_password_hash(row["password_hash"] if row else DUMMY_HASH, password)
    if not row or not valid:
        fail("Usuario o contraseña incorrectos.", 401)
    return start_session(row["id"], row["usuario"])


@api.get("/me")
@login_required
def me():
    return jsonify(usuario=g.user["usuario"], csrf_token=csrf_for(request.cookies[COOKIE]))


@api.post("/logout")
@login_required
def logout():
    db().execute("UPDATE sesiones_usuario SET revocado_en=%s WHERE token_hash=%s", (now(), digest(request.cookies[COOKIE])))
    db().commit()
    response = jsonify(ok=True)
    response.delete_cookie(COOKIE, path="/", secure=current_app.config["SESSION_COOKIE_SECURE"], httponly=True, samesite="Strict")
    return response


def audit(device_id, event, user_id=None):
    db().execute("INSERT INTO eventos_dispositivo(device_id,usuario_id,evento,ts) VALUES(%s,%s,%s,%s)",
                 (device_id, user_id, event, now()))


def lock_device(purpose):
    hashed = bearer(purpose)
    # The device row is always locked first. Revalidate credentials AFTER that lock.
    candidate = db().execute("SELECT device_id FROM credenciales_dispositivo WHERE token_hash=%s AND proposito=%s", (hashed,purpose)).fetchone()
    if candidate is None:
        fail("Credencial no válida.", 401)
    device = db().execute("SELECT * FROM dispositivos WHERE id=%s FOR UPDATE", (candidate["device_id"],)).fetchone()
    cred = db().execute("SELECT * FROM credenciales_dispositivo WHERE token_hash=%s AND proposito=%s AND revocado_en IS NULL", (hashed,purpose)).fetchone()
    if cred is None or device["bloqueado"]:
        fail("Credencial revocada o equipo bloqueado.", 401)
    return device, cred


def active_assignment(device_id):
    return db().execute("SELECT * FROM asignaciones_dispositivo WHERE device_id=%s AND fin IS NULL", (device_id,)).fetchone()


@api.post("/equipos/registro")
def register_device():
    limit("enroll-ip", client_ip(), 20, 3600)
    config_hash = bearer("config")
    data = body()
    registration_id = uuid_value(data.get("registration_id"))
    generation = uuid_value(data.get("generation"))
    measurement_hash = device_token(data.get("measurement_token"), "medicion")
    mac = string(data, "mac", 17, 17).upper()
    if not re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", mac):
        fail("MAC no válida.")
    # Serialize duplicate enrollment retries without trusting the MAC.
    db().execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (registration_id,))
    existing = db().execute("SELECT id,public_id,bloqueado FROM dispositivos WHERE registration_id=%s", (registration_id,)).fetchone()
    if existing:
        c = db().execute("SELECT 1 FROM credenciales_dispositivo WHERE device_id=%s AND proposito='config' AND token_hash=%s AND revocado_en IS NULL", (existing["id"],config_hash)).fetchone()
        if not c or existing["bloqueado"]:
            fail("No se pudo registrar esta identidad.", 409)
        db().commit()
        return jsonify(public_id=str(existing["public_id"])), 200
    ts = now()
    public_id = str(uuid.uuid4())
    row = db().execute("""INSERT INTO dispositivos(mac,nombre,primera_conexion,ultima_conexion,public_id,registration_id)
        VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""", (mac,"ESP32",ts,ts,public_id,registration_id)).fetchone()
    for purpose, hashed in [("config",config_hash),("medicion",measurement_hash)]:
        db().execute("""INSERT INTO credenciales_dispositivo(device_id,proposito,token_hash,generacion,creado_en)
            VALUES(%s,%s,%s,%s,%s)""", (row["id"],purpose,hashed,generation,ts))
    audit(row["id"], "registrado")
    db().commit()
    return jsonify(public_id=public_id), 201


def display_code(request_id):
    raw = hmac.new(current_app.config["PAIRING_PEPPER"].encode(), ("display:"+request_id).encode(), hashlib.sha256).digest()
    return base64.b32encode(raw).decode()[:12]


def code_hash(code):
    return hmac.new(current_app.config["PAIRING_PEPPER"].encode(), ("lookup:"+code).encode(), hashlib.sha256).hexdigest()


@api.post("/equipos/vinculacion")
def pairing_code():
    hashed = bearer("config")
    limit("pair-device", hashed, 12, 3600)
    data = body()
    request_id = uuid_value(data.get("request_id"))
    device, _ = lock_device("config")
    if device["owner_id"] is not None or active_assignment(device["id"]):
        fail("El equipo ya tiene propietario.", 409)
    row = db().execute("SELECT * FROM solicitudes_vinculacion WHERE id=%s", (request_id,)).fetchone()
    if row:
        if row["device_id"] != device["id"] or row["cerrada_en"] is not None or row["expira_en"] <= now():
            fail("Solicitud finalizada. Activa un código nuevo en el equipo.", 409)
        expires = row["expira_en"]
    else:
        expires = now()+600
        db().execute("UPDATE solicitudes_vinculacion SET cerrada_en=%s WHERE device_id=%s AND cerrada_en IS NULL", (now(),device["id"]))
        db().execute("INSERT INTO solicitudes_vinculacion(id,device_id,code_hash,creado_en,expira_en) VALUES(%s,%s,%s,%s,%s)",
                     (request_id,device["id"],code_hash(display_code(request_id)),now(),expires))
        audit(device["id"], "codigo_emitido")
    db().commit()
    return jsonify(code=display_code(request_id), expires_at=expires)


@api.get("/equipos/estado")
def device_status():
    hashed = bearer("config")
    limit("status-device", hashed, 30, 60)
    device, _ = lock_device("config")
    assignment = active_assignment(device["id"])
    cred = db().execute("SELECT id FROM credenciales_dispositivo WHERE device_id=%s AND proposito='medicion' AND revocado_en IS NULL AND asignacion_id=%s", (device["id"],assignment["id"] if assignment else None)).fetchone()
    db().commit()
    return jsonify(public_id=str(device["public_id"]), linked=bool(assignment), measurement_enabled=bool(cred),
                   assignment_id=assignment["id"] if assignment else None,
                   recovery_authorized=bool(assignment and device["recovery_until"] and device["recovery_until"]>now()))


@api.post("/dispositivos/vincular")
@login_required
def claim():
    limit("claim-account", g.user["id"], 10, 600)
    limit("claim-ip", client_ip(), 20, 600)
    data = body()
    code = string(data,"codigo",12,14).replace("-", "").upper()
    name = string(data,"nombre",1,40).strip()
    if not name or not re.fullmatch(r"[A-Z2-7]{12}", code):
        fail("Código o nombre no válido.")
    row = db().execute("SELECT device_id,id FROM solicitudes_vinculacion WHERE code_hash=%s", (code_hash(code),)).fetchone()
    if row is None:
        fail("Código inválido, vencido o utilizado.", 409)
    device = db().execute("SELECT * FROM dispositivos WHERE id=%s FOR UPDATE", (row["device_id"],)).fetchone()
    pairing = db().execute("SELECT * FROM solicitudes_vinculacion WHERE id=%s FOR UPDATE", (row["id"],)).fetchone()
    if device["bloqueado"] or device["owner_id"] is not None or pairing["cerrada_en"] is not None or pairing["expira_en"] <= now():
        fail("Código inválido, vencido o utilizado.", 409)
    ts = now()
    assignment = db().execute("INSERT INTO asignaciones_dispositivo(device_id,owner_id,nombre,inicio) VALUES(%s,%s,%s,%s) RETURNING id",
                              (device["id"],g.user["id"],name,ts)).fetchone()
    db().execute("UPDATE dispositivos SET owner_id=%s,nombre=%s WHERE id=%s AND owner_id IS NULL", (g.user["id"],name,device["id"]))
    db().execute("UPDATE solicitudes_vinculacion SET cerrada_en=%s,consumida_por=%s WHERE id=%s AND cerrada_en IS NULL", (ts,g.user["id"],pairing["id"]))
    # Only first enrollment has an unused measurement key. Transfer ALWAYS needs a new key.
    enabled = db().execute("UPDATE credenciales_dispositivo SET asignacion_id=%s WHERE device_id=%s AND proposito='medicion' AND revocado_en IS NULL AND asignacion_id IS NULL RETURNING id", (assignment["id"],device["id"])).fetchone()
    if not enabled:
        db().execute("UPDATE dispositivos SET recovery_until=%s WHERE id=%s", (ts+600,device["id"]))
    audit(device["id"], "vinculado", g.user["id"])
    db().commit()
    return jsonify(dispositivo={"id":device["id"],"asignacion_id":assignment["id"],"nombre":name}), 201


@api.get("/dispositivos")
@login_required
def devices():
    rows = db().execute("""SELECT a.*,d.public_id,d.ultima_conexion,d.rssi,d.bloqueado,
        EXISTS(SELECT 1 FROM credenciales_dispositivo c WHERE c.asignacion_id=a.id AND c.proposito='medicion' AND c.revocado_en IS NULL) AS envios_activos
        FROM asignaciones_dispositivo a JOIN dispositivos d ON d.id=a.device_id WHERE a.owner_id=%s ORDER BY a.id DESC""", (g.user["id"],)).fetchall()
    return jsonify(dispositivos=[dict(id=r["device_id"],asignacion_id=r["id"],nombre=r["nombre"],
        public_id=str(r["public_id"]),anterior=r["fin"] is not None,inicio=r["inicio"],fin=r["fin"],
        ultima=r["ultima_conexion"] if r["fin"] is None else r["fin"],
        en_linea=r["fin"] is None and r["envios_activos"] and not r["bloqueado"] and now()-r["ultima_conexion"]<=30,
        envios_activos=r["fin"] is None and r["envios_activos"] and not r["bloqueado"]) for r in rows])


def owned_device(device_id):
    device = db().execute("SELECT * FROM dispositivos WHERE id=%s FOR UPDATE", (device_id,)).fetchone()
    if device is None or device["owner_id"] != g.user["id"]:
        fail("Dispositivo no encontrado.", 404)
    if active_assignment(device_id) is None:
        fail("Equipo antiguo pendiente de migración de identidad.", 409)
    return device


def confirm_password(data):
    limit("sensitive-account",g.user["id"],10,600)
    password = string(data,"password",1,128)
    row = db().execute("SELECT password_hash FROM usuarios WHERE id=%s", (g.user["id"],)).fetchone()
    if not check_password_hash(row["password_hash"],password):
        fail("Contraseña incorrecta.",403)


@api.post("/dispositivos/<int:device_id>/<action>")
@login_required
def device_action(device_id, action):
    if action not in {"revocar","recuperar","liberar","bloquear"}:
        fail("Acción no encontrada.",404)
    confirm_password(body())  # rate-limit commits happen BEFORE acquiring any device lock
    device = owned_device(device_id)
    ts = now()
    if action in {"revocar","liberar","bloquear"}:
        db().execute("UPDATE credenciales_dispositivo SET revocado_en=%s WHERE device_id=%s AND proposito='medicion' AND revocado_en IS NULL", (ts,device_id))
        db().execute("UPDATE dispositivos SET recovery_until=NULL WHERE id=%s",(device_id,))
    if action == "recuperar":
        if device["bloqueado"]:
            fail("La identidad está bloqueada. Requiere reprovisionamiento físico.",409)
        db().execute("UPDATE dispositivos SET recovery_until=%s WHERE id=%s",(ts+600,device_id))
    elif action == "liberar":
        db().execute("UPDATE asignaciones_dispositivo SET fin=%s WHERE device_id=%s AND fin IS NULL",(ts,device_id))
        db().execute("UPDATE dispositivos SET owner_id=NULL WHERE id=%s",(device_id,))
        db().execute("UPDATE solicitudes_vinculacion SET cerrada_en=%s WHERE device_id=%s AND cerrada_en IS NULL",(ts,device_id))
    elif action == "bloquear":
        db().execute("UPDATE dispositivos SET bloqueado=TRUE WHERE id=%s",(device_id,))
        db().execute("UPDATE credenciales_dispositivo SET revocado_en=%s WHERE device_id=%s AND revocado_en IS NULL",(ts,device_id))
    audit(device_id,action,g.user["id"])
    db().commit()
    return jsonify(ok=True)


@api.post("/equipos/credenciales/medicion")
def rotate_measurement():
    hashed = bearer("config")
    limit("rotate-device",hashed,12,600)
    data = body()
    generation = uuid_value(data.get("generation"))
    new_hash = device_token(data.get("measurement_token"),"medicion")
    device,_ = lock_device("config")
    assignment = active_assignment(device["id"])
    if not assignment:
        fail("El equipo no está vinculado.",409)
    existing = db().execute("SELECT * FROM credenciales_dispositivo WHERE device_id=%s AND proposito='medicion' AND generacion=%s",(device["id"],generation)).fetchone()
    if existing:
        if existing["token_hash"] == new_hash and existing["revocado_en"] is None and existing["asignacion_id"] == assignment["id"]:
            db().commit()
            return jsonify(ok=True)
        fail("Generación de credencial no disponible.",409)
    if not device["recovery_until"] or device["recovery_until"] <= now():
        fail("El propietario debe autorizar la recuperación.",403)
    ts = now()
    db().execute("UPDATE credenciales_dispositivo SET revocado_en=%s WHERE device_id=%s AND proposito='medicion' AND revocado_en IS NULL",(ts,device["id"]))
    db().execute("INSERT INTO credenciales_dispositivo(device_id,proposito,token_hash,generacion,asignacion_id,creado_en) VALUES(%s,'medicion',%s,%s,%s,%s)",
                 (device["id"],new_hash,generation,assignment["id"],ts))
    db().execute("UPDATE dispositivos SET recovery_until=NULL WHERE id=%s",(device["id"],))
    audit(device["id"],"credencial_renovada",assignment["owner_id"])
    db().commit()
    return jsonify(ok=True)


def sensor_values(data):
    if set(data)-set(SENSORS)-{"rssi", "distancia_cm", "nivel_calibracion", "temperatura_estado", "temperatura_observada"}:
        fail("Campos no permitidos. La identidad se obtiene de la credencial.")
    result = {}
    for key,(_,_,lo,hi) in SENSORS.items():
        value = data.get(key)
        if value is None:
            result[key] = None
        elif isinstance(value,bool) or not isinstance(value,(int,float)) or (isinstance(value,float) and not math.isfinite(value)):
            fail(f"'{key}' debe ser un número finito.")
        elif not (lo < value < hi if key == "temperatura" else lo <= value <= hi):
            fail(f"'{key}' fuera de rango.",422)
        else:
            result[key] = float(value)
    if all(v is None for v in result.values()):
        fail("La lectura no trae valores.")
    rssi = data.get("rssi")
    if rssi is not None and (type(rssi) is not int or not -127 <= rssi <= 0):
        fail("RSSI no válido.")
    return result,rssi


def level_telemetry(data):
    distance = data.get("distancia_cm")
    if distance is not None and (type(distance) not in (int,float) or not 2 <= distance <= 400 or not math.isfinite(distance)):
        fail("Distancia del HC-SR04 no válida: utiliza centímetros entre 2 y 400.",422)
    calibration = data.get("nivel_calibracion")
    if calibration is not None and calibration != "provisional-7.8-2.0":
        fail("Referencia de calibración no admitida.",422)
    return float(distance) if distance is not None else None, calibration


def normalize_temperature(data, values):
    raw = values["temperatura"]
    provided = data.get("temperatura_estado")
    observed = data.get("temperatura_observada")
    if provided is not None and provided not in {"valida","sospechosa","invalida"}:
        fail("Estado de temperatura no válido.",422)
    if observed is not None and classify_temperature(observed) != "sospechosa":
        fail("La temperatura observada solo se admite como diagnóstico sospechoso.",422)
    state = classify_temperature(raw) if raw is not None else ("sospechosa" if observed is not None else provided or "sin_datos")
    if provided is not None and state != provided:
        fail("Temperatura y estado no coinciden.",422)
    if raw is None and state == "valida":
        fail("Falta la temperatura declarada válida.",422)
    if observed is not None and state != "sospechosa":
        fail("Diagnóstico de temperatura incoherente.",422)
    if state != "valida":
        if state == "sospechosa" and raw is not None:
            observed = raw
        values["temperatura"] = None
    return state, observed


@api.post("/lecturas")
def receive():
    hashed = bearer("medicion")
    limit("readings-device",hashed,60,60)
    data = body()
    values,rssi = sensor_values(data)
    distance,calibration = level_telemetry(data)
    temperature_state,observed_temperature = normalize_temperature(data,values)
    if all(value is None for value in values.values()):
        fail("No hay mediciones utilizables; temperatura sospechosa o inválida.",422)
    device,cred = lock_device("medicion")
    assignment = active_assignment(device["id"])
    if not assignment or cred["asignacion_id"] != assignment["id"]:
        fail("El equipo no tiene una asignación autorizada.",403)
    ts = now()
    values_to_store = (device["id"],assignment["id"],ts,values["temperatura"],values["nivel_agua"],values["turbidez"])
    metadata = {}
    if "distancia_cm" in data: metadata["distancia_cm"] = distance
    if "nivel_calibracion" in data: metadata["nivel_calibracion"] = calibration
    if data.get("temperatura_estado") is not None or temperature_state in {"sospechosa","invalida"}: metadata["temperatura_estado"] = temperature_state
    if observed_temperature is not None: metadata["temperatura_observada"] = observed_temperature
    stored_metadata = {}
    if metadata:
        columns = db().execute("""SELECT column_name FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name='lecturas'
            AND column_name IN ('distancia_cm','nivel_calibracion','temperatura_estado','temperatura_observada')""").fetchall()
        available = {row["column_name"] for row in columns}
        stored_metadata = {key:value for key,value in metadata.items() if key in available}
    # Schema 003 is optional: save core usable values even without metadata columns.
    names = ['device_id','asignacion_id','ts','temperatura','nivel_agua','turbidez']+list(stored_metadata)
    placeholders = ','.join(['%s']*len(names))
    db().execute('INSERT INTO lecturas('+','.join(names)+') VALUES('+placeholders+')', values_to_store+tuple(stored_metadata.values()))
    db().execute("UPDATE dispositivos SET ultima_conexion=%s,rssi=%s,ip=%s WHERE id=%s",(ts,rssi,client_ip(),device["id"]))
    db().commit()
    return jsonify(ok=True,intervalo_s=5,trazabilidad_guardada=len(stored_metadata)==len(metadata),temperatura_estado=temperature_state)


def user_assignment():
    assignment_id = request.args.get("asignacion_id",type=int)
    row = db().execute("""SELECT a.*,d.ultima_conexion,d.bloqueado,
        EXISTS(SELECT 1 FROM credenciales_dispositivo c WHERE c.asignacion_id=a.id AND c.proposito='medicion' AND c.revocado_en IS NULL) AS envios_activos
        FROM asignaciones_dispositivo a JOIN dispositivos d ON d.id=a.device_id
        WHERE a.id=%s AND a.owner_id=%s""",(assignment_id,g.user["id"])).fetchone()
    if not row:
        fail("Asignación no encontrada.",404)
    return row


@api.get("/publica/lecturas")
def public_readings():
    """Publish only the station selected by the operator."""
    assignment = current_app.config["PUBLIC_ASSIGNMENT_ID"]
    if not re.fullmatch(r"[1-9][0-9]{0,17}", str(assignment)):
        fail("Las mediciones p?blicas a?n no est?n configuradas.", 503)
    rows = db().execute("""
        SELECT l.ts, l.temperatura, l.nivel_agua, l.turbidez,
               (to_jsonb(l)->>'distancia_cm')::double precision AS distancia_cm,
               to_jsonb(l)->>'nivel_calibracion' AS nivel_calibracion
        FROM lecturas l
        WHERE l.asignacion_id = %s
          AND EXISTS (SELECT 1 FROM asignaciones_dispositivo a
                      WHERE a.id = l.asignacion_id AND a.fin IS NULL)
        ORDER BY l.ts DESC, l.id DESC LIMIT 120
    """, (int(assignment),)).fetchall()
    readings = []
    for row in reversed(rows):
        temperature = row["temperatura"]
        level = row["nivel_agua"]
        distance = row["distancia_cm"]
        turbidity = row["turbidez"]
        readings.append({
            "ts": row["ts"],
            "temperatura": temperature if classify_temperature(temperature) == "valida" else None,
            "nivel_agua": level if level_status(level, distance, row["nivel_calibracion"]) == "valida" else None,
            "distancia_cm": distance if distance is not None and math.isfinite(distance) and 2 <= distance <= 400 else None,
            "turbidez": turbidity if turbidity is not None and math.isfinite(turbidity) and 0 <= turbidity <= 3000 else None,
        })
    return jsonify(lecturas=readings)


@api.get("/lecturas/ultima")
@login_required
def latest():
    assignment = user_assignment()
    # JSON projection keeps reads compatible with schema 002 until migration 003 is approved.
    row = db().execute("""SELECT ts,temperatura,nivel_agua,turbidez,
        (to_jsonb(l)->>'distancia_cm')::double precision AS distancia_cm,
        to_jsonb(l)->>'nivel_calibracion' AS nivel_calibracion,
        to_jsonb(l)->>'temperatura_estado' AS temperatura_estado,
        (to_jsonb(l)->>'temperatura_observada')::double precision AS temperatura_observada
        FROM lecturas l WHERE asignacion_id=%s ORDER BY id DESC LIMIT 1""",(assignment["id"],)).fetchone()
    if not row:
        return jsonify(sin_datos=True)
    received_level = row.get("nivel_agua")
    row["nivel_estado"] = level_status(received_level,row.get("distancia_cm"),row.get("nivel_calibracion"))
    row["nivel_agua_recibido"] = received_level  # Diagnostic only; never rendered as a current level.
    if row["nivel_estado"] != "valida": row["nivel_agua"] = None
    raw_temperature = row.get("temperatura")
    state = classify_temperature(raw_temperature) if raw_temperature is not None else row.get("temperatura_estado") or "sin_datos"
    row["temperatura_estado"] = state
    if state != "valida":
        if state == "sospechosa" and raw_temperature is not None: row["temperatura_observada"] = raw_temperature
        row["temperatura"] = None
    age = now()-row["ts"]
    connection_age = now()-assignment["ultima_conexion"]
    fresh = 0 <= age <= 30 and 0 <= connection_age <= 30
    return jsonify(sin_datos=False,edad_s=age,max_edad_s=30,
                   en_linea=assignment["fin"] is None and assignment["envios_activos"] and not assignment["bloqueado"] and fresh,**row)


def evaluate(key,value):
    if key == "temperatura":
        quality = classify_temperature(value)
        if quality != "valida": return ("Sospechosa" if quality == "sospechosa" else "Inválida"),"tag-red"
        state = "Bajo" if value < 16 else "Normal" if value <= 26 else "Alto"
    elif key == "nivel_agua":
        state = "Bajo" if value < 45 else "Normal" if value <= 85 else "Alto"
    else:
        state = "Normal" if value <= 50 else "Alta"
    return state,"tag-green" if state == "Normal" else "tag-red"


@api.get("/lecturas")
@login_required
def history():
    assignment = user_assignment()
    sensor = request.args.get("sensor","Todos")
    names = {v[0]:k for k,v in SENSORS.items()}
    if sensor != "Todos" and sensor not in names:
        fail("Sensor no válido.")
    selected = [names[sensor]] if sensor != "Todos" else list(SENSORS)
    args = [request.args.get(k) for k in ("cursor_ts","cursor_id","snapshot_id")]
    cursor = None
    if any(v is not None for v in args):
        try:
            cursor = tuple(int(v) for v in args)
            if not (0 <= cursor[0] <= 2**63-1 and 1 <= cursor[1] <= cursor[2] <= 2**63-1):
                raise ValueError()
        except (ValueError,TypeError):
            fail("Cursor no válido.")
    query = "SELECT id,ts,temperatura,nivel_agua,turbidez" + (",MAX(id) OVER() AS snapshot_id" if not cursor else "") + " FROM lecturas WHERE asignacion_id=%s"
    params = [assignment["id"]]
    if sensor != "Todos":
        query += " AND " + selected[0] + " IS NOT NULL"
    if cursor:
        query += " AND id<=%s AND (ts,id)<(%s,%s)"
        params.extend((cursor[2],cursor[0],cursor[1]))
    query += " ORDER BY ts DESC,id DESC LIMIT 101"
    rows = db().execute(query,params).fetchall()
    more = len(rows)>100
    rows = rows[:100]
    records=[]
    for row in rows:
        for key in selected:
            if row[key] is not None:
                state,css=evaluate(key,row[key])
                records.append(dict(ts=row["ts"],sensor=SENSORS[key][0],valor=f"{row[key]:.1f} {SENSORS[key][1]}",estado=state,clase=css))
    next_cursor = dict(ts=rows[-1]["ts"],id=rows[-1]["id"],snapshot_id=cursor[2] if cursor else rows[0]["snapshot_id"]) if more else None
    return jsonify(registros=records,cursor=next_cursor)
