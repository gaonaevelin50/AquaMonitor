"""
Simulador de ESP32 para probar AquaMonitor SIN hardware.

Envía lecturas falsas cada pocos segundos, igual que lo haría el ESP32 real.
Uso:
    python simulador_esp32.py
    python simulador_esp32.py --alertas        (valores que se salen de rango)
    python simulador_esp32.py --host https://tu-proyecto.vercel.app --key TU_API_KEY --mac AA:BB:CC:DD:EE:02
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description="Simulador de ESP32 para AquaMonitor")
parser.add_argument("--host", default="http://localhost:5000", help="Dirección del servidor")
parser.add_argument("--key", default="AQUAMONITOR_API_KEY_PLACEHOLDER", help="API key (igual a la de app.py)")
parser.add_argument("--mac", default="AA:BB:CC:DD:EE:01", help="MAC falsa del dispositivo")
parser.add_argument("--intervalo", type=float, default=5, help="Segundos entre lecturas")
parser.add_argument("--alertas", action="store_true", help="Variar más para provocar alertas")
args = parser.parse_args()

paso = 6 if args.alertas else 1
valores = {"temperatura": 23.0, "nivel_agua": 70.0, "turbidez": 15.0, "ph": 7.2}
limites = {"temperatura": (10, 35), "nivel_agua": (10, 100), "turbidez": (0, 100), "ph": (4, 10)}
variacion = {"temperatura": 0.4, "nivel_agua": 1.5, "turbidez": 2.0, "ph": 0.1}

print(f"Simulando {args.mac} -> {args.host}  (Ctrl+C para detener)")
while True:
    for k in valores:
        valores[k] += random.uniform(-1, 1) * variacion[k] * paso
        valores[k] = min(max(valores[k], limites[k][0]), limites[k][1])

    cuerpo = {k: round(v, 1) for k, v in valores.items()}
    cuerpo.update({"mac": args.mac, "rssi": random.randint(-75, -50)})

    peticion = urllib.request.Request(
        args.host.rstrip("/") + "/api/lecturas",
        data=json.dumps(cuerpo).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": args.key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=5) as resp:
            print("OK ", resp.status, cuerpo)
    except urllib.error.HTTPError as e:
        print("ERROR", e.code, e.read().decode())
    except urllib.error.URLError as e:
        print("No se pudo conectar al servidor:", e.reason)
    time.sleep(args.intervalo)
