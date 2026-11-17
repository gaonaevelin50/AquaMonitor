"""Simulador de desarrollo del protocolo individual; no valida sensores físicos.
Nunca utiliza ni acepta AQUAMONITOR_API_KEY. No ejecutarlo contra producción sin autorización.
"""
import argparse
import json
from pathlib import Path
import random
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='http://127.0.0.1:5000')
    parser.add_argument('--state',default='.test-runtime/simulator-identity.json')
    parser.add_argument('--pair',action='store_true',help='Solicitar un código temporal nuevo')
    parser.add_argument('--intervalo',type=float,default=5)
    args=parser.parse_args()
    origin=urllib.parse.urlsplit(args.host)
    if origin.scheme!='https' and not (origin.scheme=='http' and origin.hostname in {'localhost','127.0.0.1'}):
        parser.error('Solo se permite HTTP para localhost; fuera del equipo usa HTTPS.')
    if args.intervalo<5:
        parser.error('El intervalo mínimo es de 5 segundos.')
    state_path=Path(args.state)
    if state_path.exists():
        state=json.loads(state_path.read_text(encoding='utf-8'))
    else:
        state=dict(config='ac_'+secrets.token_hex(32),measurement='am_'+secrets.token_hex(32),
                   registration_id=str(uuid.uuid4()),generation=str(uuid.uuid4()))
    def save():
        state_path.parent.mkdir(parents=True,exist_ok=True)
        temp=state_path.with_suffix('.tmp')
        temp.write_text(json.dumps(state),encoding='utf-8')
        temp.replace(state_path)
    save()
    def call(route,payload=None,token=None):
        request=urllib.request.Request(args.host.rstrip('/')+'/api'+route,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type':'application/json','Authorization':'Bearer '+(token or state['config'])})
        with urllib.request.urlopen(request,timeout=10) as response:
            return json.load(response)
    try:
        if not state.get('public_id'):
            reply=call('/equipos/registro',dict(registration_id=state['registration_id'],generation=state['generation'],
                measurement_token=state['measurement'],mac='AA:BB:CC:DD:EE:01'))
            state['public_id']=reply['public_id']; save()
        if args.pair:
            code=call('/equipos/vinculacion',dict(request_id=str(uuid.uuid4())))
            print('Código temporal de vinculación:',code['code'])
        while True:
            status=call('/equipos/estado')
            if status['linked'] and (status['recovery_authorized'] or state.get('pending_token')):
                if not state.get('pending_token'):
                    state['pending_token']='am_'+secrets.token_hex(32)
                    state['pending_generation']=str(uuid.uuid4()); save()
                call('/equipos/credenciales/medicion',dict(generation=state['pending_generation'],measurement_token=state['pending_token']))
                state['measurement']=state.pop('pending_token'); state['generation']=state.pop('pending_generation'); save()
                status['measurement_enabled']=True
            if status['measurement_enabled']:
                call('/lecturas',dict(temperatura=round(random.uniform(20,25),1),nivel_agua=70,turbidez=15,rssi=-60),token=state['measurement'])
                print('Lectura simulada enviada.')
            else:
                print('Esperando vinculación o recuperación autorizada.')
            time.sleep(args.intervalo)
    except urllib.error.HTTPError as exc:
        print('Solicitud rechazada, HTTP',exc.code,'; no se muestran detalles privados.')
    except (urllib.error.URLError,TimeoutError):
        print('Conexión no disponible. Conserva el archivo de identidad y vuelve a ejecutar.')
    except KeyboardInterrupt:
        print('Simulador detenido; identidad conservada.')


if __name__=='__main__':
    main()
