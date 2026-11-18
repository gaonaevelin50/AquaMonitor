import unittest
from unittest.mock import patch
from flask import Flask
from level_quality import level_status,CALIBRATION_ID
import aquamonitor_api as api
from tests.test_level_trace import MemoryDB

class LevelProvenance(unittest.TestCase):
    def test_legacy_percentage_is_never_current_without_distance(self):
        self.assertEqual(level_status(87.6,None,None),"sin_distancia_valida")
        app=Flask(__name__)
        original={"ts":1000,"temperatura":30.1,"nivel_agua":87.6,"turbidez":12}
        assignment={"id":2,"fin":None,"envios_activos":True,"bloqueado":False,"ultima_conexion":1000}
        with app.test_request_context(),patch.object(api,"now",return_value=1000),patch.object(api,"user_assignment",return_value=assignment),patch.object(api,"db",return_value=MemoryDB(original.copy())):
            data=api.latest.__wrapped__().json
            self.assertTrue(data["en_linea"]);self.assertIsNone(data["nivel_agua"])
            self.assertEqual(data["nivel_agua_recibido"],87.6)
            self.assertEqual(data["temperatura"],30.1);self.assertEqual(original["nivel_agua"],87.6)
    def test_api_preserves_verified_percentage_exactly(self):
        row={"ts":1000,"temperatura":30.1,"nivel_agua":71.2,"turbidez":12,"distancia_cm":3.67,"nivel_calibracion":CALIBRATION_ID}
        assignment={"id":2,"fin":None,"envios_activos":True,"bloqueado":False,"ultima_conexion":1000}
        with Flask(__name__).test_request_context(),patch.object(api,"now",return_value=1000),patch.object(api,"user_assignment",return_value=assignment),patch.object(api,"db",return_value=MemoryDB(row.copy())):
            data=api.latest.__wrapped__().json
            self.assertEqual(data["nivel_estado"],"valida");self.assertEqual(data["nivel_agua"],71.2)
    def test_valid_received_values_are_not_recalculated(self):
        for percent,distance in ((0,7.8),(0,8.11),(25,6.35),(50,4.9),(75,3.45),(71.2,3.67),(95,2.29),(100,2.0),(87.6,2.72)):
            self.assertEqual(level_status(percent,distance,CALIBRATION_ID),"valida")
    def test_incompatible_or_unidentified_calibration_is_rejected(self):
        self.assertEqual(level_status(87.6,8.11,CALIBRATION_ID),"calibracion_incompatible")
        self.assertEqual(level_status(50,4.9,None),"calibracion_no_identificada")
        self.assertEqual(level_status(50,4.9,"legacy-30-5"),"calibracion_no_identificada")
        self.assertEqual(level_status(0,7.79,CALIBRATION_ID),"calibracion_incompatible")
    def test_restored_wave_uses_historical_colors_svg_and_shape(self):
        from pathlib import Path
        import subprocess,re
        old=subprocess.check_output(["git","show","3dcb48f:public/styles.css"],text=True,encoding="utf-8")
        new=Path("public/styles.css").read_text(encoding="utf-8")
        svg=re.search(r'url\("(data:image/svg\+xml,[^"\n]+)',old).group(1)
        self.assertIn(svg,new)
        self.assertIn("linear-gradient(180deg, #58CFC6 0%, #1B7F8A 100%)",new)
        self.assertIn("animation: ola 6s linear infinite",new)
        def glass(text):return re.search(r"\.tanque-vidrio\s*\{([^}]+)\}",text).group(1).split()
        self.assertEqual(glass(old),glass(new))
    def test_invalid_and_missing_values_do_not_become_zero(self):
        for distance in (None,-1,0,1.99,401,float("nan"),float("inf"),True,"7.8"):
            self.assertNotEqual(level_status(0,distance,CALIBRATION_ID),"valida")
        for percent in (None,-1,101,float("nan"),True,"0"):
            self.assertNotEqual(level_status(percent,7.8,CALIBRATION_ID),"valida")

if __name__=="__main__":unittest.main()
