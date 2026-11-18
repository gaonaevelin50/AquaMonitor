"""AquaMonitor: Flask API and local dashboard. Migrations are always explicit."""
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent


def create_app(overrides=None):
    production = bool(os.environ.get("VERCEL"))
    app = Flask(__name__, static_folder=None if production else "public", static_url_path="")
    app.config.update(
        DATABASE_URL=os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL", ""),
        SECRET_KEY=os.environ.get("SECRET_KEY", ""),
        PAIRING_PEPPER=os.environ.get("AQUAMONITOR_PAIRING_PEPPER", ""),
        DB_SCHEMA_READY=os.environ.get("AQUAMONITOR_DB_SCHEMA_READY", "").lower() in {"true", "1", "yes"},
        DB_SSLMODE=os.environ.get("AQUAMONITOR_DB_SSLMODE", "verify-full"),
        DB_SSLROOTCERT=os.environ.get("AQUAMONITOR_DB_SSLROOTCERT", ""),
        SESSION_COOKIE_SECURE=production,
        MAX_CONTENT_LENGTH=8192,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )
    if production:
        # Only Vercel's managed proxy may supply the forwarded HTTPS scheme.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=0, x_port=0, x_prefix=0)
    if overrides:
        app.config.update(overrides)
    if production and (len(app.config["SECRET_KEY"]) < 32 or len(app.config["PAIRING_PEPPER"]) < 32):
        raise RuntimeError("Configure SECRET_KEY y AQUAMONITOR_PAIRING_PEPPER independientes, de al menos 32 caracteres.")

    if production and (app.config["DB_SSLMODE"] != "verify-full" or app.config["SECRET_KEY"] == app.config["PAIRING_PEPPER"]):
        raise RuntimeError("Producción requiere verify-full y dos secretos de servidor independientes.")

    @app.before_request
    def schema_guard():
        if request.path.startswith("/api/"):
            if not app.config["DB_SCHEMA_READY"] or not app.config["PAIRING_PEPPER"] or not app.config["SECRET_KEY"]:
                return jsonify(detail="Configure las variables de seguridad y aplique las migraciones 001 y 002 antes de habilitar la API."), 503
            db = get_db()
            try:
                row = db.execute("SELECT version FROM aquamonitor_migraciones WHERE version=2").fetchone()
            except psycopg.errors.UndefinedTable:
                db.rollback()
                return jsonify(detail="Falta aplicar la migración 002. No se ejecuta automáticamente."), 503
            if row is None:
                return jsonify(detail="Falta la migración 002."), 503

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.after_request
    def secure_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(Exception)
    def controlled_error(exc):
        db = g.get("db")
        if db is not None:
            db.rollback()
        if isinstance(exc, HTTPException):
            return jsonify(detail="Solicitud no válida."), exc.code
        if isinstance(exc, psycopg.IntegrityError):
            return jsonify(detail="La operación entró en conflicto. Actualiza y vuelve a intentarlo."), 409
        if isinstance(exc, psycopg.Error):
            # Log only a fixed category: never the exception/connection string.
            message = str(exc).lower()
            category = "tls_ca" if any(t in message for t in ("certificate", "root.crt", "verify locations")) else "connection_or_query"
            app.logger.error("database_error category=%s sqlstate=%s", category, exc.sqlstate or "none")
            return jsonify(detail="Servicio de datos temporalmente no disponible."), 503
        # Never log exception bodies: database errors can include private connection data.
        app.logger.error("Fallo interno: %s", type(exc).__name__)
        return jsonify(detail="Error interno del servidor."), 500

    app.extensions["aquamonitor_get_db"] = get_db
    from aquamonitor_api import api
    app.register_blueprint(api)
    if not production:
        @app.get("/")
        @app.get("/monitoreo")
        @app.get("/admin.html")
        def index():
            return send_from_directory(BASE_DIR / "public", "index.html")
    return app


def get_db():
    if "db" not in g:
        from flask import current_app
        cfg = current_app.config
        kwargs = dict(row_factory=dict_row, connect_timeout=5, sslmode=cfg["DB_SSLMODE"])
        if cfg["DB_SSLROOTCERT"]:
            if cfg["DB_SSLROOTCERT"] == "system":
                # OpenSSL's default CA path differs across serverless runtimes.
                # Supply a trusted Mozilla bundle while retaining system + verify-full.
                import certifi
                os.environ.setdefault("SSL_CERT_FILE", certifi.where())
            kwargs["sslrootcert"] = cfg["DB_SSLROOTCERT"]
        g.db = psycopg.connect(cfg["DATABASE_URL"], **kwargs)
    return g.db


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
