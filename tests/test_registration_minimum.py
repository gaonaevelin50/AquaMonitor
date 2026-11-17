"""Registration/login regression checks with an in-memory database only."""
import unittest
from unittest.mock import patch
from flask import Flask
from werkzeug.security import check_password_hash
import aquamonitor_api as api

class MemoryDB:
    def __init__(self): self.user=None; self.sessions={}; self.row=None
    def execute(self,sql,args):
        if sql.startswith("INSERT INTO usuarios"):
            self.user={"id":1,"usuario":args[0],"password_hash":args[1]}; self.row=self.user
        elif sql.startswith("INSERT INTO sesiones_usuario"):
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
    def test_four_rejected_and_five_registered(self):
        self.assertEqual(self.post("/registro",{"usuario":"abcde","password":"abcd"}).status_code,400)
        self.assertIsNone(self.db.user)
        r=self.post("/registro",{"usuario":"abcde","password":"abcde"})
        self.assertEqual(r.status_code,201)
        self.assertNotEqual(self.db.user["password_hash"],"abcde")
        self.assertTrue(check_password_hash(self.db.user["password_hash"],"abcde"))
        cookie=r.headers["Set-Cookie"]
        for flag in ("Secure","HttpOnly","SameSite=Strict"):self.assertIn(flag,cookie)
    def test_five_login_session_and_csrf_preserved(self):
        r=self.post("/registro",{"usuario":"abcde","password":"abcde"})
        self.assertEqual(r.status_code,201)
        self.assertEqual(self.client.get("/api/me",base_url="https://localhost").status_code,200)
        self.assertEqual(self.post("/logout",{}).status_code,403)
        self.assertEqual(self.post("/logout",{}, {"X-CSRF-Token":r.json["csrf_token"]}).status_code,200)
        self.assertEqual(self.client.get("/api/me",base_url="https://localhost").status_code,401)
        self.assertEqual(self.post("/login",{"usuario":"abcde","password":"abcde"}).status_code,200)

if __name__=="__main__":unittest.main()
