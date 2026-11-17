"""Level-only contract checks. All database operations use an in-memory fake."""
import json
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch
from flask import Flask
import aquamonitor_api as api

class LevelContract(unittest.TestCase):
    def test_received_percentage_is_stored_unchanged(self):
        app = Flask(__name__)
        class DB:
            def __init__(self): self.inserted = None
            def execute(self, sql, args):
                if sql.startswith("INSERT INTO lecturas"): self.inserted = args
                return self
            def commit(self): pass
        for value in (0.0, 50.0, 100.0, None):
            payload = {"temperatura": 23.4, "turbidez": 10.0}
            if value is not None: payload["nivel_agua"] = value
            fake = DB()
            with app.test_request_context(json=payload), patch.object(api,"bearer",return_value="test"), patch.object(api,"limit"), patch.object(api,"lock_device",return_value=({"id":1},{"asignacion_id":2})), patch.object(api,"active_assignment",return_value={"id":2}), patch.object(api,"db",return_value=fake):
                self.assertTrue(api.receive().get_json()["ok"])
                self.assertEqual(fake.inserted[4],value)

    def test_history_uses_same_percentage_and_skips_invalid_level(self):
        app = Flask(__name__)
        class DB:
            def __init__(self,value): self.value=value
            def execute(self,*args): return self
            def fetchall(self):
                return [{"id":1,"snapshot_id":1,"ts":1700000000,"temperatura":23.4,"nivel_agua":self.value,"turbidez":10.0}]
        for value in (0.0,50.0,100.0,None):
            with app.test_request_context("/api/lecturas?asignacion_id=2"), patch.object(api,"user_assignment",return_value={"id":2}), patch.object(api,"db",return_value=DB(value)):
                rows=api.history.__wrapped__().get_json()["registros"]
                levels=[r for r in rows if r["sensor"]=="Nivel de Agua"]
                self.assertEqual([r["valor"] for r in levels],[] if value is None else [f"{value:.1f} %"])

    def test_dashboard_displays_received_percentage(self):
        source=Path("public/script.js").read_text(encoding="utf-8")
        function=re.search(r"function procesarSensores\(\) \{.*?^\}",source,re.S|re.M).group(0)
        code="""const vm=require('vm'); const assert=require('assert');
const fn=JSON.parse(process.argv[1]);
for(const value of [0,50,100,null]) {
 const updates=[]; const missing=[];
 const ctx={sensores:{temperatura:null,nivelAgua:value,turbidez:null,nivelEstado:"valida",nivelCalibracion:"provisional-7.8-2.0",distanciaCm:value===0?8.11:value===50?4.9:2},actualizarUI:(...args)=>updates.push(args),sinSensor:id=>missing.push(id)};
 vm.runInNewContext(fn+';procesarSensores();',ctx);
 const level=updates.find(args=>args[0]==='nivelAgua');
 if(value===null){assert.strictEqual(level[1],'--');assert.strictEqual(level[4],null);}
 else {assert.strictEqual(level[1],value);assert.strictEqual(level[4],value);}
}
console.log('PASS dashboard 0/50/100/null without recalibration');"""
        result=subprocess.run(["node","-e",code,json.dumps(function)],capture_output=True,text=True,check=True)
        self.assertIn("PASS dashboard",result.stdout)

if __name__=="__main__": unittest.main()
