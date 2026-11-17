"""Run the current local AquaMonitor against the confirmed Neon pruebas host."""
from pathlib import Path
import sys
from urllib.parse import urlsplit, parse_qsl
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
values = dotenv_values(ROOT / ".env")
raw = values.get("DATABASE_URL") or ""
uri = urlsplit(raw)
expected = (values.get("NEON_PRUEBAS_HOST") or "").strip().lower()
if not expected or uri.hostname != expected or not expected.endswith(".neon.tech"):
    raise SystemExit("Arranque bloqueado: DATABASE_URL no coincide con el host confirmado de pruebas.")
if any(key.lower() in {"host","hostaddr","service","options"} for key,_ in parse_qsl(uri.query)):
    raise SystemExit("Arranque bloqueado: la conexion intenta reemplazar el destino.")
secret = values.get("SECRET_KEY") or ""
pepper = values.get("AQUAMONITOR_PAIRING_PEPPER") or ""
if len(secret)<32 or len(pepper)<32 or secret==pepper:
    raise SystemExit("Arranque bloqueado: faltan secretos de servidor independientes.")
from app import create_app
app = create_app(dict(DATABASE_URL=raw,SECRET_KEY=secret,PAIRING_PEPPER=pepper,
                      DB_SCHEMA_READY=True,DB_SSLMODE="verify-full",DB_SSLROOTCERT="system",
                      SESSION_COOKIE_SECURE=False))
# DB_SCHEMA_READY never applies migrations: the existing version 2 guard still runs.
# The non-Secure cookie is confined to local HTTP; Vercel continues using Secure.
if __name__ == "__main__":
    print("AquaMonitor local actual: http://127.0.0.1:5000 ; Neon pruebas; TLS verify-full",flush=True)
    app.run(host="127.0.0.1",port=5000,debug=False,use_reloader=False)
