"""Configure ONLY aquamonitor Preview. No deploy, Git commands, or production changes.
Secret values are read from .env and sent to Vercel exclusively through stdin.
"""
import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qsl, urlsplit
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "prj_OoK2snM9wpvxGWQsKVXDyGDHM8Zz"
ORG_ID = "team_luSNUUgqrBBRk5h42XmGP31h"
SCOPE = "rota-smart1"
CLI = ROOT / ".test-runtime/vercel-cli/node_modules/vercel/dist/vc.js"


def stop(message):
    print(message)
    raise SystemExit(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--save-pepper',action='store_true')
    mode.add_argument('--upload-env',action='store_true')
    args=parser.parse_args()
    values=dotenv_values(ROOT/'.env')
    if args.save_pepper:
        if not sys.stdin.isatty():
            stop('Ejecuta --save-pepper directamente en una terminal interactiva para ocultar la entrada.')
        existing=values.get('AQUAMONITOR_PAIRING_PEPPER')
        if existing:
            stop('La variable ya existe. No se sobrescribió ningún secreto.')
        secret=getpass('Pega tu AQUAMONITOR_PAIRING_PEPPER generado (entrada oculta): ').strip()
        if len(secret)<32 or secret==values.get('SECRET_KEY'):
            stop('Debe tener al menos 32 caracteres y ser diferente de SECRET_KEY. No se guardó.')
        set_key(str(ROOT/'.env'),'AQUAMONITOR_PAIRING_PEPPER',secret)
        print('Secreto guardado localmente, sin mostrar su valor. No se realizó despliegue.')
        return
    linked=ROOT/'.vercel/project.json'
    if not linked.is_file() or not CLI.is_file():
        stop('Falta la vinculación local o Vercel CLI.')
    project=json.loads(linked.read_text(encoding='utf-8'))
    if project.get('projectId')!=PROJECT_ID or project.get('orgId')!=ORG_ID:
        stop('Proyecto distinto del AquaMonitor nuevo. Operación bloqueada.')
    raw=values.get('DATABASE_URL') or ''
    uri=urlsplit(raw)
    host=(values.get('NEON_PRUEBAS_HOST') or '').strip().lower()
    if not host or uri.hostname!=host or not host.endswith('.neon.tech'):
        stop('DATABASE_URL no coincide con el Host de pruebas confirmado. Operación bloqueada.')
    if any(k.lower() in {'host','hostaddr','service','options'} for k,_ in parse_qsl(uri.query)):
        stop('La conexión contiene una anulación de destino no permitida.')
    secret=values.get('SECRET_KEY') or ''
    pepper=values.get('AQUAMONITOR_PAIRING_PEPPER') or ''
    if len(secret)<32 or len(pepper)<32 or secret==pepper:
        stop('Faltan los dos secretos distintos de al menos 32 caracteres. No se subió ninguna variable.')
    variables={
        'DATABASE_URL':raw,
        'SECRET_KEY':secret,
        'AQUAMONITOR_PAIRING_PEPPER':pepper,
        'AQUAMONITOR_DB_SCHEMA_READY':'true',
        'AQUAMONITOR_DB_SSLMODE':'verify-full',
        'AQUAMONITOR_DB_SSLROOTCERT':'system',
    }
    child_env=dict(os.environ,VERCEL_TELEMETRY_DISABLED='1',NO_COLOR='1')
    for name,value in variables.items():
        # No secret on argv. Capture CLI output: never echo raw stdout/stderr.
        command=['node',str(CLI),'env','add',name,'--environment','preview',
                 '--project',PROJECT_ID,'--scope',SCOPE,'--yes','--force',
                 '--sensitive' if name in {'DATABASE_URL','SECRET_KEY','AQUAMONITOR_PAIRING_PEPPER'} else '--no-sensitive']
        result=subprocess.run(command,input=value,encoding='utf-8',stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,cwd=ROOT,env=child_env,timeout=90)
        if result.returncode:
            stop(f'No se pudo configurar {name} en Preview. Salida privada de CLI omitida; no se desplegó.')
        print(f'{name}: configurada exclusivamente en Preview.')
    print('Las seis variables Preview quedaron configuradas. No se realizó despliegue.')


if __name__=='__main__':
    main()
