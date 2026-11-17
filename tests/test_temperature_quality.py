import unittest
from unittest.mock import patch
from flask import Flask
import aquamonitor_api as api
from temperature_quality import classify_temperature

class TemperatureQuality(unittest.TestCase):
    def test_digital_and_physical_classes(self):
        for value in (0,30.1,50):self.assertEqual(classify_temperature(value),"valida")
        for value in (-55,-0.1,50.1,99.7,125):self.assertEqual(classify_temperature(value),"sospechosa")
        for value in (-127,-55.1,85,126,float("nan"),float("inf"),True,None):self.assertEqual(classify_temperature(value),"invalida")
    def test_legacy_99_7_is_diagnostic_not_current(self):
        values={"temperatura":99.7,"nivel_agua":50,"turbidez":12}
        with Flask(__name__).test_request_context():
            state,observed=api.normalize_temperature({},values)
            self.assertEqual((state,observed),("sospechosa",99.7));self.assertIsNone(values["temperatura"])
    def test_new_firmware_diagnostic_kept_separate(self):
        values={"temperatura":None,"nivel_agua":50,"turbidez":12}
        with Flask(__name__).test_request_context():
            state,observed=api.normalize_temperature({"temperatura_estado":"sospechosa","temperatura_observada":99.7},values)
            self.assertEqual((state,observed),("sospechosa",99.7));self.assertIsNone(values["temperatura"])
    def test_latest_hides_legacy_anomaly_without_rewriting_row(self):
        from tests.test_level_trace import MemoryDB
        row={"ts":1000,"temperatura":99.7,"nivel_agua":50,"turbidez":12}
        assignment={"id":2,"fin":None,"envios_activos":True,"bloqueado":False,"ultima_conexion":1000}
        with Flask(__name__).test_request_context(),patch.object(api,"now",return_value=1000),patch.object(api,"user_assignment",return_value=assignment),patch.object(api,"db",return_value=MemoryDB(row.copy())):
            data=api.latest.__wrapped__().json
            self.assertIsNone(data["temperatura"]);self.assertEqual(data["temperatura_estado"],"sospechosa");self.assertEqual(data["temperatura_observada"],99.7)
            self.assertEqual(row["temperatura"],99.7)
    def test_inconsistent_diagnostic_rejected(self):
        from werkzeug.exceptions import HTTPException
        with Flask(__name__).test_request_context():
            with self.assertRaises(HTTPException):
                api.normalize_temperature({"temperatura_estado":"valida","temperatura_observada":99.7},{"temperatura":30,"nivel_agua":50,"turbidez":12})
            with self.assertRaises(HTTPException):
                api.normalize_temperature({"temperatura_estado":"valida"},{"temperatura":None,"nivel_agua":50,"turbidez":12})
    def test_history_labels_raw_anomaly_explicitly(self):
        self.assertEqual(api.evaluate("temperatura",99.7)[0],"Sospechosa")
        self.assertEqual(api.evaluate("temperatura",85)[0],"Inválida")

if __name__=="__main__":unittest.main()
