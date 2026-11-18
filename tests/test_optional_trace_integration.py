"""Schema-002/003 upgrade checks restricted to a new disposable local database."""
import secrets
import uuid
import unittest
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from app import create_app
from werkzeug.security import generate_password_hash

ROOT=Path(__file__).resolve().parents[1]
class OptionalTraceIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name="aquamonitor_sensor_"+uuid.uuid4().hex
        admin="host=127.0.0.1 port=55439 user=aquamonitor_test dbname=postgres sslmode=disable"
        with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.name)))
        cls.dsn=f"host=127.0.0.1 port=55439 user=aquamonitor_test dbname={cls.name} sslmode=disable"
        with psycopg.connect(cls.dsn) as c:
            for name in ("001_initial_schema.sql","002_secure_devices.sql"):c.execute((ROOT/"migrations"/name).read_text(encoding="utf-8"),prepare=False)
        cls.app=create_app(dict(TESTING=True,DATABASE_URL=cls.dsn,DB_SCHEMA_READY=True,DB_SSLMODE="disable",SECRET_KEY="s"*64,PAIRING_PEPPER="p"*64,SESSION_COOKIE_SECURE=False))
    def test_optional_upgrade_preserves_core_and_historical_rows(self):
        client=self.app.test_client()
        with psycopg.connect(self.dsn) as c:
            c.execute("INSERT INTO usuarios(usuario,password_hash,creado_en) VALUES (%s,%s,1)",
                      ("local_sensor_owner",generate_password_hash("abcde")))
        r=client.post("/api/login",json={"usuario":"local_sensor_owner","password":"abcde"});self.assertEqual(r.status_code,200);csrf=r.json["csrf_token"]
        config="ac_"+secrets.token_hex(32);measure="am_"+secrets.token_hex(32)
        def machine(path,data=None,token=config):return client.open("/api"+path,method="GET" if data is None else "POST",json=data,headers={"Authorization":"Bearer "+token})
        self.assertEqual(machine("/equipos/registro",{"registration_id":str(uuid.uuid4()),"generation":str(uuid.uuid4()),"measurement_token":measure,"mac":"02:00:00:00:00:61"}).status_code,201)
        code=machine("/equipos/vinculacion",{"request_id":str(uuid.uuid4())}).json["code"]
        r=client.post("/api/dispositivos/vincular",json={"codigo":code,"nombre":"Solo test local"},headers={"X-CSRF-Token":csrf});self.assertEqual(r.status_code,201)
        device=r.json["dispositivo"];assignment=device["asignacion_id"]
        payload={"temperatura_estado":"sospechosa","temperatura_observada":99.7,"nivel_agua":50,"turbidez":12,"distancia_cm":4.9,"nivel_calibracion":"provisional-7.8-2.0"}
        r=machine("/lecturas",payload,measure);self.assertEqual(r.status_code,200);self.assertFalse(r.json["trazabilidad_guardada"])
        with psycopg.connect(self.dsn,row_factory=dict_row) as c:
            row=c.execute("SELECT * FROM lecturas ORDER BY id DESC LIMIT 1").fetchone()
            self.assertIsNone(row["temperatura"]);self.assertEqual(row["nivel_agua"],50)
            # New local fixture simulates a pre-correction historical raw value.
            historical=c.execute("INSERT INTO lecturas(device_id,asignacion_id,ts,temperatura,nivel_agua,turbidez) VALUES(%s,%s,1,99.7,71.2,12) RETURNING *",(device["id"],assignment)).fetchone()
            c.commit()
            c.execute((ROOT/"migrations/003_level_trace.sql").read_text(encoding="utf-8"),prepare=False)
            after=c.execute("SELECT * FROM lecturas WHERE id=%s",(historical["id"],)).fetchone()
            for key,value in historical.items():self.assertEqual(after[key],value)
            self.assertIsNone(after["temperatura_estado"])
        r=machine("/lecturas",payload,measure);self.assertEqual(r.status_code,200);self.assertTrue(r.json["trazabilidad_guardada"])
        latest=client.get("/api/lecturas/ultima",query_string={"asignacion_id":assignment}).json
        self.assertIsNone(latest["temperatura"]);self.assertEqual(latest["temperatura_observada"],99.7);self.assertEqual(latest["temperatura_estado"],"sospechosa");self.assertEqual(latest["distancia_cm"],4.9)
        with psycopg.connect(self.dsn,row_factory=dict_row) as c:
            row=c.execute("SELECT * FROM lecturas ORDER BY id DESC LIMIT 1").fetchone()
            self.assertIsNone(row["temperatura"]);self.assertEqual(row["temperatura_observada"],99.7)
        r=machine("/lecturas",{"temperatura":30,"nivel_agua":50,"temperatura_estado":None},measure)
        self.assertEqual(r.status_code,200)
        history=client.get("/api/lecturas",query_string={"asignacion_id":assignment}).json["registros"]
        self.assertTrue(any(item["valor"]=="99.7 °C" and item["estado"]=="Sospechosa" for item in history))

if __name__=="__main__":unittest.main()
