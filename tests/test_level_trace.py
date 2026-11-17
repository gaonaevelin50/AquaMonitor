"""Water-level provenance/freshness checks; no external DB or device access."""
import unittest
from unittest.mock import patch
from flask import Flask
import psycopg
import aquamonitor_api as api

class MemoryDB:
    def __init__(self,row=None,missing=False):self.row=row;self.missing=missing;self.args=None;self.rolled_back=False
    def execute(self,query,args=None):
        if query.startswith("INSERT INTO lecturas"):
            if self.missing and "distancia_cm" in query:raise AssertionError("Must use legacy columns without migration")
            self.args=args
        return self
    def fetchall(self):return [] if self.missing else [{"column_name":k} for k in ("distancia_cm","nivel_calibracion","temperatura_estado","temperatura_observada")]
    def fetchone(self):return self.row
    def commit(self):pass
    def rollback(self):self.rolled_back=True

class LevelTrace(unittest.TestCase):
    def test_new_metadata_stores_received_percentage_without_recalculation(self):
        app=Flask(__name__);db=MemoryDB()
        data={"temperatura":23.4,"nivel_agua":95.0,"turbidez":12.0,"distancia_cm":2.29,"nivel_calibracion":"provisional-7.8-2.0"}
        with app.test_request_context(json=data),patch.object(api,"bearer",return_value="test"),patch.object(api,"limit"),patch.object(api,"lock_device",return_value=({"id":1},{"asignacion_id":2})),patch.object(api,"active_assignment",return_value={"id":2}),patch.object(api,"db",return_value=db):
            self.assertTrue(api.receive().get_json()["ok"])
            self.assertEqual(db.args[4],95.0);self.assertEqual(db.args[6:],(2.29,"provisional-7.8-2.0"))
    def test_metadata_is_optional_without_schema_update(self):
        app=Flask(__name__);app.register_blueprint(api.api);db=MemoryDB(missing=True)
        with patch.object(api,"bearer",return_value="test"),patch.object(api,"limit"),patch.object(api,"lock_device",return_value=({"id":1},{"asignacion_id":2})),patch.object(api,"active_assignment",return_value={"id":2}),patch.object(api,"db",return_value=db):
            response=app.test_client().post("/api/lecturas",json={"nivel_agua":50,"distancia_cm":4.9})
            self.assertEqual(response.status_code,200);self.assertFalse(response.json["trazabilidad_guardada"]);self.assertFalse(db.rolled_back);self.assertEqual(len(db.args),6)
    def test_invalid_distance_rejected(self):
        app=Flask(__name__);app.register_blueprint(api.api)
        with patch.object(api,"bearer",return_value="test"),patch.object(api,"limit"):
            for invalid in (True,1.9,401,"4.9",float("nan"),float("inf")):
                response=app.test_client().post("/api/lecturas",json={"nivel_agua":50,"distancia_cm":invalid})
                self.assertEqual(response.status_code,422)
    def test_latest_uses_reading_age_not_only_connection_age(self):
        app=Flask(__name__)
        for ts,expected in ((995,True),(940,False),(1060,False)):
            row={"ts":ts,"temperatura":23,"nivel_agua":95,"turbidez":12,"distancia_cm":None,"nivel_calibracion":None}
            assignment={"id":2,"fin":None,"envios_activos":True,"bloqueado":False,"ultima_conexion":1000}
            with app.test_request_context(),patch.object(api,"now",return_value=1000),patch.object(api,"user_assignment",return_value=assignment),patch.object(api,"db",return_value=MemoryDB(row)):
                response=api.latest.__wrapped__().get_json()
                self.assertEqual(response["en_linea"],expected);self.assertEqual(response["edad_s"],1000-ts)
                self.assertIsNone(response["nivel_agua"]);self.assertEqual(response["nivel_agua_recibido"],95)
                self.assertIsNone(response["distancia_cm"])

if __name__=="__main__":unittest.main()
