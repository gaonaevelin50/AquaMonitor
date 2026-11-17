"""Disposable local UI server. Never reads a deployment connection string."""
from pathlib import Path
import secrets
import sys
import uuid
import psycopg
from psycopg import sql

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app

name='aquamonitor_test_ui_'+uuid.uuid4().hex
admin='host=127.0.0.1 port=55439 user=aquamonitor_test dbname=postgres sslmode=disable'
with psycopg.connect(admin,autocommit=True) as c:
    c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
dsn=f'host=127.0.0.1 port=55439 user=aquamonitor_test dbname={name} sslmode=disable'
with psycopg.connect(dsn) as c:
    for migration in ['001_initial_schema.sql','002_secure_devices.sql']:
        c.execute((ROOT/'migrations'/migration).read_text(encoding='utf-8'),prepare=False)
app=create_app(dict(DATABASE_URL=dsn,DB_SCHEMA_READY=True,DB_SSLMODE='disable',
    SECRET_KEY=secrets.token_hex(32),PAIRING_PEPPER=secrets.token_hex(32),SESSION_COOKIE_SECURE=False))
print('Disposable local UI database:',name,flush=True)
app.run(host='127.0.0.1',port=5059,debug=False,use_reloader=False)
