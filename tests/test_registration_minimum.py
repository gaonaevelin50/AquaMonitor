"""Invitation-only login regression checks with an in-memory database only."""
import unittest
from unittest.mock import patch
from flask import Flask
from werkzeug.security import generate_password_hash
import aquamonitor_api as api

class MemoryDB:
    def __init__(self):
        self.user = {"id": 1, "usuario": "abcde", "password_hash": generate_password_hash("abcde")}
        self.sessions = {}
        self.row = None
    def execute(self,sql,args):
        if sql.startswith("INSERT INTO sesiones_usuario"):
            self.sessions[args[0]]=True
        elif sql.startswith("SELECT * FROM usuarios"):
            self.row=self.user if self.user and self.user["usuario"]==args[0] else None
        elif sql.startswith("SELECT u.id,u.usuario"):
            self.row=self.user if self.sessions.get(args[0]) else None
        elif sql.startswith("UPDATE sesiones_usuario"):
            self.sessions[args[1]]=False
        else: raise AssertionError("Unexpected query in memory-only test")
        return self
    def fetchone(self): return self.row
    def commit(self): pass

class RegistrationMinimum(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__)
        self.app.config.update(SECRET_KEY="s"*64,PAIRING_PEPPER="p"*64,SESSION_COOKIE_SECURE=True)
        self.app.register_blueprint(api.api)
        self.db=MemoryDB()
        self.patches=[patch.object(api,"db",return_value=self.db),patch.object(api,"limit")]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.client=self.app.test_client()
    def post(self,path,data,headers=None):
        return self.client.post("/api"+path,json=data,headers=headers or {},base_url="https://localhost")
    def test_public_registration_unavailable_and_login_cookie_secure(self):
        self.assertEqual(self.post("/registro", {"usuario": "visitante", "password": "abcde"}).status_code, 404)
        r = self.post("/login", {"usuario": "abcde", "password": "abcde"})
        self.assertEqual(r.status_code, 200)
        cookie=r.headers["Set-Cookie"]
        for flag in ("Secure","HttpOnly","SameSite=Strict"):self.assertIn(flag,cookie)
    def test_private_charts_require_session_and_public_feed_is_gone(self):
        self.assertEqual(self.client.get("/api/lecturas/graficas").status_code, 401)
        self.assertEqual(self.client.get("/api/publica/lecturas").status_code, 404)

    def test_five_login_session_and_csrf_preserved(self):
        r=self.post("/login",{"usuario":"abcde","password":"abcde"})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get("/api/me",base_url="https://localhost").status_code,200)
        self.assertEqual(self.post("/logout",{}).status_code,403)
        self.assertEqual(self.post("/logout",{}, {"X-CSRF-Token":r.json["csrf_token"]}).status_code,200)
        self.assertEqual(self.client.get("/api/me",base_url="https://localhost").status_code,401)
        self.assertEqual(self.post("/login",{"usuario":"abcde","password":"abcde"}).status_code,200)

if __name__=="__main__":unittest.main()
