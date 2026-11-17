"""Explicit synthetic WiFi protocol check against AquaMonitor Preview / Neon pruebas.
Never reads physical device tokens, flashes hardware or deletes existing records.
"""
import hashlib
import http.client
import http.cookiejar
import json
import re
import secrets
import ssl
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl

import certifi
from dotenv import dotenv_values
import psycopg

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://aquamonitor-ot2xvv3ux-rota-smart1.vercel.app"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class HTTP10Connection(http.client.HTTPSConnection):
    _http_vsn = 10
    _http_vsn_str = "HTTP/1.0"

class HTTP10Handler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(HTTP10Connection, req, context=self._context)


def run():
    env = dotenv_values(ROOT / ".env")
    raw = env.get("DATABASE_URL") or ""
    uri = urlsplit(raw)
    expected = (env.get("NEON_PRUEBAS_HOST") or "").strip().lower()
    assert expected and uri.hostname == expected and expected.endswith(".neon.tech"), "Pruebas host guard"
    assert not any(k.lower() in {"host", "hostaddr", "service", "options"} for k, _ in parse_qsl(uri.query)), "Connection override guard"
    source = (ROOT / "esp32/aquamonitor_esp32/secrets.h").read_text(encoding="utf-8")
    def macro(name):
        m = re.search(r'^\s*#define\s+' + name + r'\s+("(?:\\.|[^"\\])*")', source, re.M)
        assert m, "Private macro missing"
        return json.loads(m.group(1))
    assert macro("AQUAMONITOR_SERVER_URL") == ORIGIN + "/api/lecturas", "Preview-only firmware URL"
    context = ssl.create_default_context(cadata=macro("AQUAMONITOR_ROOT_CA"))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    jar = http.cookiejar.CookieJar()
    machine = urllib.request.build_opener(NoRedirect(), HTTP10Handler(context=context))
    browser = urllib.request.build_opener(NoRedirect(), HTTP10Handler(context=context), urllib.request.HTTPCookieProcessor(jar))
    csrf = None
    def call(path, payload=None, token=None, user=False):
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if user and csrf:
            headers["X-CSRF-Token"] = csrf
        request = urllib.request.Request(ORIGIN + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try:
            with (browser if user else machine).open(request, timeout=30) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, {}
    def check(label, ok):
        if not ok:
            raise RuntimeError(label)
        print("PASS", label, flush=True)
    config = "ac_" + secrets.token_hex(32)
    measurement = "am_" + secrets.token_hex(32)
    registration_id = str(uuid.uuid4())
    registration = {"registration_id": registration_id, "generation": str(uuid.uuid4()), "measurement_token": measurement,
                    "mac": "02:" + ":".join(secrets.token_hex(1) for _ in range(5))}
    status, data = call("/api/equipos/registro", registration, config)
    check("registration_https_tls12_http10", status == 201 and str(uuid.UUID(data["public_id"])) == data["public_id"])
    # Confirm this exact Preview registration exists in the separately guarded pruebas connection.
    with psycopg.connect(raw, sslmode="verify-full", sslrootcert=certifi.where(), options="-c default_transaction_read_only=on") as db:
        row = db.execute("SELECT public_id FROM dispositivos WHERE registration_id=%s", (registration_id,)).fetchone()
        check("preview_registration_confirmed_in_neon_pruebas", row is not None and str(row[0]) == data["public_id"])
    before = int(time.time())
    status, data = call("/api/equipos/vinculacion", {"request_id": str(uuid.uuid4())}, config)
    check("backend_code_real_and_not_expired", status == 200 and re.fullmatch(r"[A-Z2-7]{12}", data["code"]) and before < data["expires_at"] <= int(time.time()) + 601)
    code = data["code"]
    username = "wifiqa_" + secrets.token_hex(5)
    password = secrets.token_urlsafe(32)
    status, data = call("/api/registro", {"usuario": username, "password": password}, user=True)
    check("synthetic_test_account_created", status == 201)
    csrf = data["csrf_token"]
    status, _ = call("/api/logout", {}, user=True)
    check("test_account_logout", status == 200)
    status, data = call("/api/login", {"usuario": username, "password": password}, user=True)
    check("owner_login", status == 200)
    csrf = data["csrf_token"]
    status, data = call("/api/dispositivos/vincular", {"codigo": code, "nombre": "QA WiFi TLS HTTP10"}, user=True)
    check("backend_code_links_named_device", status == 201)
    device = data["dispositivo"]
    status, data = call("/api/equipos/estado", token=config)
    check("device_receives_linked_enabled_status", status == 200 and data["linked"] and data["measurement_enabled"] and data["assignment_id"] == device["asignacion_id"])
    values = {"temperatura": 23.4, "nivel_agua": 67.8, "turbidez": 12.3, "rssi": -60}
    for index in range(2):
        values["temperatura"] = 23.4 + index
        status, _ = call("/api/lecturas", values, measurement)
        check("measurement_accepted_" + str(index + 1), status == 200)
    query = "?asignacion_id=" + str(device["asignacion_id"])
    status, data = call("/api/lecturas/ultima" + query, user=True)
    check("dashboard_three_values_confirmed", status == 200 and all(data[k] == values[k] for k in ("temperatura", "nivel_agua", "turbidez")))
    status, data = call("/api/lecturas" + query, user=True)
    check("history_grows_to_six_sensor_rows", status == 200 and len(data["registros"]) == 6)
    status, _ = call("/api/dispositivos/vincular", {"codigo": code, "nombre": "No reutilizable"}, user=True)
    check("backend_code_is_single_use", status == 409)
    call("/api/logout", {}, user=True)
    report = {"origin": ORIGIN, "neon_pruebas_verified": True, "tls": "TLSv1.2", "http": "HTTP/1.0",
              "synthetic": True, "physical_firmware_uploaded": False, "history_rows": 6,
              "registration_id": registration_id, "assignment_id": device["asignacion_id"]}
    (ROOT / ".test-runtime/wifi-flow-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("WIFI_FLOW_PREVIEW_VERIFIED; SYNTHETIC_CLIENT_ONLY; NO_PHYSICAL_UPLOAD", flush=True)

if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print("WIFI_FLOW_CHECK_FAILED", type(exc).__name__, flush=True)
        raise SystemExit(1)
