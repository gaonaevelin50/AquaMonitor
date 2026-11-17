"""Explicit HTTPS contract probe for the approved AquaMonitor Preview only.
Creates a clearly named synthetic account/device in Neon pruebas. Never uses
real device secrets, prints tokens/codes, changes Production or uploads firmware.
"""
import http.cookiejar
import json
import re
import secrets
import urllib.error
import urllib.request
import uuid

ORIGIN = "https://aquamonitor-ot2xvv3ux-rota-smart1.vercel.app"


def main():
    jar=http.cookiejar.CookieJar()
    user=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    machine=urllib.request.build_opener()
    config="ac_"+secrets.token_hex(32)
    measurement="am_"+secrets.token_hex(32)
    password=secrets.token_hex(32)
    csrf=None
    def call(path,payload=None,token=None,as_user=False,legacy=False):
        headers={"Accept":"application/json","Content-Type":"application/json"}
        if token: headers["Authorization"]="Bearer "+token
        if legacy: headers["X-API-Key"]="legacy-protocol-probe-invalid"
        if as_user and csrf: headers["X-CSRF-Token"]=csrf
        req=urllib.request.Request(ORIGIN+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        try:
            with (user if as_user else machine).open(req,timeout=30) as r:
                assert r.url.startswith(ORIGIN+"/"), "Unexpected redirect"
                return r.status,json.load(r)
        except urllib.error.HTTPError as exc:
            try: data=json.load(exc)
            except Exception: data={}
            return exc.code,data
    def check(label,condition):
        if not condition: raise RuntimeError(label)
        print("PASS",label,flush=True)
    payload={"temperatura":23.4,"nivel_agua":67.8,"turbidez":12.3,"rssi":-60}
    status,_=call("/api/lecturas",payload,legacy=True)
    check("legacy_global_key_rejected",status==401)
    status,_=call("/api/equipos/estado",token=measurement)
    check("measurement_key_cannot_configure",status==401)
    registration={"registration_id":str(uuid.uuid4()),"generation":str(uuid.uuid4()),"measurement_token":measurement,"mac":"02:00:00:00:00:41"}
    status,data=call("/api/equipos/registro",registration,token=config)
    check("individual_registration",status==201 and str(uuid.UUID(data["public_id"]))==data["public_id"])
    status,_=call("/api/equipos/registro",registration,token=config)
    check("registration_retry_idempotent",status==200)
    status,state=call("/api/equipos/estado",token=config)
    check("state_before_link",status==200 and state["linked"] is False and state["measurement_enabled"] is False)
    status,_=call("/api/lecturas",payload,token=measurement)
    check("unlinked_reading_rejected",status==403)
    request_id=str(uuid.uuid4())
    status,data=call("/api/equipos/vinculacion",{"request_id":request_id},token=config)
    check("temporary_code_format",status==200 and bool(re.fullmatch(r"[A-Z2-7]{12}",data["code"])))
    code=data["code"]
    status,retry=call("/api/equipos/vinculacion",{"request_id":request_id},token=config)
    check("code_retry_idempotent",status==200 and retry["code"]==code)
    status,data=call("/api/registro",{"usuario":"fwqa_"+secrets.token_hex(5),"password":password},as_user=True)
    check("synthetic_owner_registered",status==201)
    csrf=data["csrf_token"]
    status,data=call("/api/dispositivos/vincular",{"codigo":code,"nombre":"Prueba protocolo firmware"},as_user=True)
    check("code_links_device_to_owner",status==201)
    device=data["dispositivo"]
    status,_=call("/api/dispositivos/vincular",{"codigo":code,"nombre":"Reintento"},as_user=True)
    check("code_single_use",status==409)
    status,state=call("/api/equipos/estado",token=config)
    check("state_after_link",status==200 and state["linked"] and state["measurement_enabled"] and state["assignment_id"]==device["asignacion_id"])
    status,_=call("/api/lecturas",payload,token=measurement)
    check("firmware_measurement_payload_accepted",status==200)
    status,data=call("/api/lecturas/ultima?asignacion_id="+str(device["asignacion_id"]),as_user=True)
    check("dashboard_measurements_persisted",status==200 and all(data[k]==payload[k] for k in ["temperatura","nivel_agua","turbidez"]))
    status,data=call("/api/lecturas?asignacion_id="+str(device["asignacion_id"]),as_user=True)
    check("history_three_sensor_rows",status==200 and len(data["registros"])==3)
    status,_=call("/api/dispositivos/"+str(device["id"])+"/revocar",{"password":password},as_user=True)
    check("owner_revokes_measurement_key",status==200)
    status,_=call("/api/lecturas",payload,token=measurement)
    check("revoked_measurement_rejected",status==401)
    status,state=call("/api/equipos/estado",token=config)
    check("configuration_channel_survives_measurement_revocation",status==200 and state["linked"] and not state["measurement_enabled"])
    call("/api/logout",{},as_user=True)
    print("PROTOCOL_PREVIEW_VERIFIED: synthetic client only; physical ESP32 not flashed or verified.")


if __name__=="__main__":
    try: main()
    except Exception as exc:
        print("PROTOCOL_PROBE_FAILED",type(exc).__name__)
        raise SystemExit(1)
