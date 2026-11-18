"""Integration tests: ONLY the disposable local cluster at 127.0.0.1:55439.
Never reads DATABASE_URL for test connections and never connects to Neon.
Run: python -B -m unittest discover -s tests -v
"""
import concurrent.futures
import hashlib
import os
from pathlib import Path
import re
import secrets
import unittest
import uuid

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from werkzeug.security import generate_password_hash
from app import create_app

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "test-password-only-123"
ADMIN = "host=127.0.0.1 port=55439 user=aquamonitor_test dbname=postgres sslmode=disable"


class SecureIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name = "aquamonitor_test_" + uuid.uuid4().hex
        # Fail closed: an unavailable local cluster never falls back to .env or Neon.
        with psycopg.connect(ADMIN,autocommit=True) as c:
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.name)))
        cls.dsn = f"host=127.0.0.1 port=55439 user=aquamonitor_test dbname={cls.name} sslmode=disable"
        with psycopg.connect(cls.dsn) as c:
            c.execute((ROOT/'migrations/001_initial_schema.sql').read_text(encoding='utf-8'),prepare=False)
            c.execute("INSERT INTO usuarios(usuario,password_hash,creado_en) VALUES('legacy','not-a-password',1)")
            c.execute("INSERT INTO dispositivos(mac,nombre,owner_id,primera_conexion,ultima_conexion) VALUES('AA:BB:CC:DD:EE:FF','legacy',1,1,1)")
            c.execute("INSERT INTO lecturas(device_id,ts,temperatura) VALUES(1,1,20)")
            c.commit()
            c.execute((ROOT/'migrations/002_secure_devices.sql').read_text(encoding='utf-8'),prepare=False)
            row=c.execute("SELECT asignacion_id,temperatura FROM lecturas WHERE id=1").fetchone()
            assert row == (None,20.0), "Migration must preserve readings without guessing ownership"
            assert c.execute("SELECT owner_id FROM dispositivos WHERE id=1").fetchone()[0] == 1
        cls.app=create_app(dict(TESTING=True,DATABASE_URL=cls.dsn,DB_SCHEMA_READY=True,
            SECRET_KEY=secrets.token_hex(32),PAIRING_PEPPER=secrets.token_hex(32),DB_SSLMODE='disable',SESSION_COOKIE_SECURE=False))

    def setUp(self):
        with self.connection() as c:
            c.execute("TRUNCATE sesiones_usuario,eventos_dispositivo,solicitudes_vinculacion,credenciales_dispositivo,lecturas,asignaciones_dispositivo,dispositivos,usuarios,limites_seguridad,intentos_login RESTART IDENTITY CASCADE")
        self.a=self.app.test_client(); self.b=self.app.test_client()
        self.csrf={}
        for client,name in [(self.a,'alice'),(self.b,'bob')]:
            with psycopg.connect(self.dsn) as c:
                c.execute("INSERT INTO usuarios(usuario,password_hash,creado_en) VALUES (%s,%s,1)",
                          (name,generate_password_hash(PASSWORD)))
            r=client.post('/api/login',json=dict(usuario=name,password=PASSWORD))
            self.assertEqual(r.status_code,200)
            self.csrf[id(client)]=r.json['csrf_token']
        self.config='ac_'+secrets.token_hex(32); self.measure='am_'+secrets.token_hex(32)
        self.generation=str(uuid.uuid4()); self.registration=str(uuid.uuid4())
        self.enroll=dict(registration_id=self.registration,generation=self.generation,measurement_token=self.measure,mac='AA:BB:CC:DD:EE:FF')
        r=self.equipment('/equipos/registro',self.enroll)
        self.assertEqual(r.status_code,201)
        self.public=r.json['public_id']

    @classmethod
    def tearDownClass(cls):
        # Keep isolated test database for review; no production cleanup/destructive operations.
        print("Local test database retained:",cls.name)

    def connection(self):
        return psycopg.connect(self.dsn,row_factory=dict_row)

    def equipment(self,path,data=None,token=None,method='POST'):
        return self.app.test_client().open('/api'+path,method=method,json=data,
            headers={'Authorization':'Bearer '+(token or self.config)})

    def user(self,client,path,data):
        return client.post('/api'+path,json=data,headers={'X-CSRF-Token':self.csrf[id(client)]})

    def code(self):
        self.request_id=str(uuid.uuid4())
        r=self.equipment('/equipos/vinculacion',dict(request_id=self.request_id))
        self.assertEqual(r.status_code,200)
        return r.json['code']

    def claim(self,client=None,code=None):
        r=self.user(client or self.a,'/dispositivos/vincular',dict(codigo=code or self.code(),nombre='Estanque'))
        self.assertEqual(r.status_code,201)
        return r.json['dispositivo']

    def reading(self,token=None,**values):
        return self.equipment('/lecturas',values or dict(temperatura=23,nivel_agua=70,turbidez=12,rssi=-60),token=token or self.measure)

    def action(self,device,action,client=None):
        return self.user(client or self.a,f"/dispositivos/{device['id']}/{action}",dict(password=PASSWORD))

    def test_registration_retry_and_mac_is_not_identity(self):
        self.assertEqual(self.equipment('/equipos/registro',self.enroll).status_code,200)
        new_config='ac_'+secrets.token_hex(32)
        self.assertEqual(self.equipment('/equipos/registro',self.enroll,token=new_config).status_code,409)
        second=dict(self.enroll,registration_id=str(uuid.uuid4()),measurement_token='am_'+secrets.token_hex(32))
        r=self.equipment('/equipos/registro',second,token=new_config)
        self.assertEqual(r.status_code,201)
        self.assertNotEqual(r.json['public_id'],self.public)

    def test_pairing_retry_and_success(self):
        code=self.code()
        r=self.equipment('/equipos/vinculacion',dict(request_id=self.request_id))
        self.assertEqual(code,r.json['code'])
        self.claim(code=code)
        self.assertTrue(self.equipment('/equipos/estado',method='GET').json['linked'])
        self.assertEqual(self.equipment('/equipos/vinculacion',dict(request_id=str(uuid.uuid4()))).status_code,409)

    def test_reused_code(self):
        code=self.code(); self.claim(code=code)
        self.assertEqual(self.user(self.b,'/dispositivos/vincular',dict(codigo=code,nombre='Intruso')).status_code,409)

    def test_expired_code(self):
        code=self.code()
        with self.connection() as c:
            c.execute('UPDATE solicitudes_vinculacion SET creado_en=1,expira_en=2')
        self.assertEqual(self.user(self.a,'/dispositivos/vincular',dict(codigo=code,nombre='Estanque')).status_code,409)

    def test_concurrent_claim_one_winner(self):
        code=self.code()
        def run(client):
            return self.user(client,'/dispositivos/vincular',dict(codigo=code,nombre='Concurrente')).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,[self.a,self.b]))
        self.assertEqual(sorted(results),[201,409])
        with self.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM asignaciones_dispositivo WHERE fin IS NULL').fetchone()['n'],1)

    def test_valid_reading_and_wrong_credentials(self):
        d=self.claim()
        self.assertEqual(self.reading().status_code,200)
        self.assertEqual(self.reading(token='am_'+secrets.token_hex(32)).status_code,401)
        self.assertEqual(self.reading(token=self.config).status_code,401)
        self.assertEqual(self.a.get('/api/lecturas/ultima',query_string=dict(asignacion_id=d['asignacion_id'])).json['temperatura'],23)
        self.assertEqual(self.app.test_client().post('/api/lecturas',json={'mac':'AA:BB:CC:DD:EE:FF'},headers={'X-API-Key':'obsolete'}).status_code,401)

    def test_unlinked_and_identity_injection(self):
        self.assertEqual(self.reading().status_code,403)
        self.claim()
        self.assertEqual(self.reading(mac='AA:AA:AA:AA:AA:AA',temperatura=22).status_code,400)
        self.assertEqual(self.reading(device_id=99,temperatura=22).status_code,400)

    def test_revocation_and_authorized_recovery(self):
        d=self.claim(); self.assertEqual(self.action(d,'revocar').status_code,200)
        self.assertEqual(self.reading().status_code,401)
        new='am_'+secrets.token_hex(32); generation=str(uuid.uuid4())
        rotation=dict(generation=generation,measurement_token=new)
        self.assertEqual(self.equipment('/equipos/credenciales/medicion',rotation).status_code,403)
        self.assertEqual(self.action(d,'recuperar',self.b).status_code,404)
        self.assertEqual(self.action(d,'recuperar').status_code,200)
        self.assertTrue(self.equipment('/equipos/estado',method='GET').json['recovery_authorized'])
        self.assertEqual(self.equipment('/equipos/credenciales/medicion',rotation).status_code,200)
        self.assertEqual(self.equipment('/equipos/credenciales/medicion',rotation).status_code,200)
        self.assertEqual(self.reading(token=new).status_code,200)
        self.assertEqual(self.reading().status_code,401)

    def test_transfer_and_history_isolation(self):
        old=self.claim(); self.assertEqual(self.reading(temperatura=21).status_code,200)
        self.assertEqual(self.action(old,'liberar').status_code,200)
        self.assertEqual(self.reading().status_code,401)
        new=self.claim(self.b)
        token='am_'+secrets.token_hex(32)
        self.assertEqual(self.equipment('/equipos/credenciales/medicion',dict(generation=str(uuid.uuid4()),measurement_token=token)).status_code,200)
        self.assertEqual(self.reading(token=token,temperatura=25).status_code,200)
        for client,own,other,temp in [(self.a,old,new,21),(self.b,new,old,25)]:
            r=client.get('/api/lecturas',query_string=dict(asignacion_id=own['asignacion_id']))
            self.assertEqual(r.status_code,200)
            self.assertEqual(len(r.json['registros']),1)
            self.assertTrue(r.json['registros'][0]['valor'].startswith(str(temp)))
            self.assertEqual(client.get('/api/lecturas',query_string=dict(asignacion_id=other['asignacion_id'])).status_code,404)
            charts=client.get('/api/lecturas/graficas',query_string=dict(asignacion_id=own['asignacion_id']))
            self.assertEqual(charts.status_code,200)
            self.assertEqual([r['temperatura'] for r in charts.json['lecturas']],[temp])
            self.assertEqual(client.get('/api/lecturas/graficas',query_string=dict(asignacion_id=other['asignacion_id'])).status_code,404)
        self.assertTrue(self.a.get('/api/dispositivos').json['dispositivos'][0]['anterior'])

    def test_isolation_password_csrf_and_logout(self):
        d=self.claim()
        self.assertEqual(self.b.get('/api/dispositivos').json['dispositivos'],[])
        self.assertEqual(self.action(d,'revocar',self.b).status_code,404)
        self.assertEqual(self.a.post(f"/api/dispositivos/{d['id']}/revocar",json=dict(password=PASSWORD)).status_code,403)
        self.assertEqual(self.user(self.a,f"/dispositivos/{d['id']}/revocar",dict(password='wrong')).status_code,403)
        cookie=self.a.get_cookie('aquamonitor_session').value
        self.assertEqual(self.user(self.a,'/logout',{}).status_code,200)
        stolen=self.app.test_client(); stolen.set_cookie('aquamonitor_session',cookie)
        self.assertEqual(stolen.get('/api/me').status_code,401)

    def test_block_identity_and_no_reset_takeover(self):
        d=self.claim(); self.assertEqual(self.action(d,'bloquear').status_code,200)
        self.assertEqual(self.equipment('/equipos/estado',method='GET').status_code,401)
        self.assertEqual(self.equipment('/equipos/registro',self.enroll).status_code,409)
        self.assertEqual(self.reading().status_code,401)

    def test_limits_and_no_frontend_secrets(self):
        for _ in range(10):
            r=self.user(self.a,'/dispositivos/vincular',dict(codigo='A'*12,nombre='Test'))
            self.assertEqual(r.status_code,409)
        self.assertEqual(self.user(self.a,'/dispositivos/vincular',dict(codigo='A'*12,nombre='Test')).status_code,429)
        self.claim(self.b)
        response=self.b.get('/api/dispositivos')
        self.assertNotIn(self.measure,response.text); self.assertNotIn(self.config,response.text)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        with self.connection() as c:
            hashes=[x['token_hash'] for x in c.execute('SELECT token_hash FROM credenciales_dispositivo')]
        self.assertIn(hashlib.sha256(self.config.encode()).hexdigest(),hashes)

    def test_sensor_validation_and_json(self):
        self.claim()
        for data,status in [([1],400),({'temperatura':True},400),({'temperatura':-50},422),({'temperatura':100},422),({'temperatura':10**400},422),({'temperatura':float('nan')},400),({'turbidez':3001},422),({'nivel_agua':-1},422),({'rssi':1,'temperatura':20},400),({},400)]:
            self.assertEqual(self.equipment('/lecturas',data,token=self.measure).status_code,status)
        self.assertEqual(self.reading(temperatura=22,nivel_agua=0,turbidez=100).status_code,200)
        self.assertIn(self.a.post('/api/registro',json=[1]).status_code,(404,405))
        self.assertEqual(self.a.post('/api/login',json={'usuario':'alice','password':'x'},headers={'Origin':'https://evil.invalid'}).status_code,403)

    def test_history_pagination_and_legacy_exclusion(self):
        d=self.claim()
        with self.connection() as c:
            c.execute('INSERT INTO lecturas(device_id,ts,temperatura) VALUES(%s,1,99)',(d['id'],))
            for i in range(105):
                c.execute('INSERT INTO lecturas(device_id,asignacion_id,ts,temperatura) VALUES(%s,%s,%s,20)',(d['id'],d['asignacion_id'],i+1))
        params=dict(asignacion_id=d['asignacion_id'],sensor='Temperatura')
        first=self.a.get('/api/lecturas',query_string=params).json
        self.assertEqual(len(first['registros']),100)
        cursor=first['cursor']; params.update(cursor_ts=cursor['ts'],cursor_id=cursor['id'],snapshot_id=cursor['snapshot_id'])
        second=self.a.get('/api/lecturas',query_string=params).json
        self.assertEqual(len(second['registros']),5); self.assertIsNone(second['cursor'])
        self.assertTrue(all('99.0' not in r['valor'] for r in first['registros']+second['registros']))


    def test_recovery_expiry_and_revoked_generation(self):
        d=self.claim()
        self.action(d,'revocar'); self.action(d,'recuperar')
        with self.connection() as c:
            c.execute('UPDATE dispositivos SET recovery_until=1 WHERE id=%s',(d['id'],))
        token='am_'+secrets.token_hex(32); generation=str(uuid.uuid4())
        rotation=dict(generation=generation,measurement_token=token)
        self.assertEqual(self.equipment('/equipos/credenciales/medicion',rotation).status_code,403)
        self.action(d,'recuperar')
        self.assertEqual(self.equipment('/equipos/credenciales/medicion',rotation).status_code,200)
        self.action(d,'revocar'); self.action(d,'recuperar')
        self.assertEqual(self.equipment('/equipos/credenciales/medicion',rotation).status_code,409)
        self.assertEqual(self.reading(token=token).status_code,401)

    def test_pending_old_rotation_cannot_write_after_transfer(self):
        old=self.claim()
        self.action(old,'revocar'); self.action(old,'recuperar')
        token='am_'+secrets.token_hex(32)
        rotation=dict(generation=str(uuid.uuid4()),measurement_token=token)
        self.assertEqual(self.equipment('/equipos/credenciales/medicion',rotation).status_code,200)
        self.action(old,'liberar')
        new=self.claim(self.b)
        self.assertEqual(self.equipment('/equipos/credenciales/medicion',rotation).status_code,409)
        self.assertEqual(self.reading(token=token).status_code,401)
        with self.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM lecturas WHERE asignacion_id=%s',(new['asignacion_id'],)).fetchone()['n'],0)

    def test_revoke_waits_for_inflight_device_lock(self):
        d=self.claim()
        lock=self.connection()
        try:
            lock.execute('SELECT id FROM dispositivos WHERE id=%s FOR UPDATE',(d['id'],))
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(self.reading)
                lock.execute("UPDATE credenciales_dispositivo SET revocado_en=1 WHERE device_id=%s AND proposito='medicion'",(d['id'],))
                lock.commit()
                self.assertEqual(future.result(timeout=20).status_code,401)
            with self.connection() as c:
                self.assertEqual(c.execute('SELECT count(*) AS n FROM lecturas').fetchone()['n'],0)
        finally:
            lock.close()

    def test_disabled_schema_and_production_configuration(self):
        app=create_app(dict(DATABASE_URL='',DB_SCHEMA_READY=False,PAIRING_PEPPER=''))
        self.assertEqual(app.test_client().get('/api/me').status_code,503)
        with self.connection() as c:
            c.execute('DELETE FROM aquamonitor_migraciones WHERE version=2')
        try:
            self.assertEqual(self.a.get('/api/me').status_code,503)
        finally:
            with self.connection() as c:
                c.execute('INSERT INTO aquamonitor_migraciones(version) VALUES(2)')
        from unittest.mock import patch
        with patch.dict(os.environ,{'VERCEL':'1','SECRET_KEY':'s'*32,'AQUAMONITOR_PAIRING_PEPPER':'p'*32}):
            production=create_app(dict(DATABASE_URL='',DB_SCHEMA_READY=False))
            from flask import request
            @production.get('/origin-probe')
            def origin_probe():
                return {'origin':request.host_url}
            probe=production.test_client().get('/origin-probe',headers={'X-Forwarded-Proto':'https','Host':'example.invalid'})
            self.assertEqual(probe.json['origin'],'https://example.invalid/')
            self.assertTrue(production.config['SESSION_COOKIE_SECURE'])
            self.assertEqual(production.config['DB_SSLMODE'],'verify-full')
            response=production.test_client().get('/api/me')
            self.assertEqual(response.status_code,503)
            self.assertIn('Strict-Transport-Security',response.headers)
            with self.assertRaises(RuntimeError):
                create_app(dict(DB_SSLMODE='disable'))


class FirmwareContract(unittest.TestCase):
    def test_sensor_parameters_and_tls(self):
        text=(ROOT/'esp32/aquamonitor_esp32/aquamonitor_esp32.ino').read_text(encoding='utf-8')
        for name,value in [('pinDatosDS18B20','4'),('trigPin','5'),('echoPin','18'),('pinTurbidez','34'),('ADC_AGUA_CLARA','2205'),('ADC_AGUA_TURBIA','1000'),('NTU_MAXIMO','100.0'),('MUESTRAS','20')]:
            self.assertRegex(text,rf"\b{name}\s*=\s*{re.escape(value)}\s*;")
        for formula in ['duracion * 0.0343 / 2.0','raw = suma / MUESTRAS','(float)(ADC_AGUA_CLARA - ADC_AGUA_TURBIA)']:
            self.assertIn(formula,text)
        self.assertIn('(DIST_SENSOR_FONDO_CM - distanciaCm)',text)
        self.assertIn('(DIST_SENSOR_FONDO_CM - DIST_SENSOR_LLENO_CM) * 100.0',text)
        self.assertIn('#include "water_level.h"',text)
        self.assertNotIn('setInsecure(',text)
        network=(ROOT/'esp32/aquamonitor_esp32/secure_network.h').read_text(encoding='utf-8') if (ROOT/'esp32/aquamonitor_esp32/secure_network.h').exists() else text
        self.assertIn('setCACert(ROOT_CA_CERT)',network)


if __name__=='__main__':
    unittest.main()
