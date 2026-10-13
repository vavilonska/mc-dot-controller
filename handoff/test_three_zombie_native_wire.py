"""Consume production Java-emitted three-mode receipts with both strict codecs.

Run after ThreeZombieReceiptEmissionTest to use fresh mainline output; otherwise
use the separately labelled frozen synthetic fixture. No transport/game calls.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
MAINLINE=ROOT
HARNESS=ROOT/'test-tools/encounter-stage1.1-safety-v2'
sys.path[:0]=[str(MAINLINE/'resident-controller'),str(HARNESS)]
from resident_controller.encounter_contract import validate_encounter_request,validate_encounter_receipt
from encounter_contract import validate_encounter_receipt as harness_validate

GENERATED=MAINLINE/'client-mod/build/encounter-fixtures/three-zombie-receipts.json'
FIXTURE=HARNESS/'fixtures/three-zombie-native-emitted-receipts.json'

class NativeThreeModeWire(unittest.TestCase):
    def test_fresh_or_frozen_native_emissions_pass_real_python_and_javascript_codecs(self):
        source=GENERATED if GENERATED.exists() else FIXTURE
        cases=json.loads(source.read_text())['cases'];self.assertEqual(len(cases),8)
        for case in cases:
            with self.subTest(case=case['name']):
                validate_encounter_request(case['request'])
                validate_encounter_receipt(case['receipt'],case['request'])
                harness_validate(case['receipt'],case['request'])
        module=(MAINLINE/'client-mod/mcp/encounter-contract.mjs').as_uri()
        script=f"""import fs from 'node:fs';import {{validateEncounterRequest,validateEncounterReceipt}} from {json.dumps(module)};
const cases=JSON.parse(fs.readFileSync(process.argv[1],'utf8')).cases;
for(const c of cases){{validateEncounterRequest(c.request);validateEncounterReceipt(c.receipt,c.request);}}
process.stdout.write('Java-produced receipts accepted by actual JS codec: '+cases.length+'\\n');"""
        subprocess.run(['node','--input-type=module','-e',script,str(source)],check=True)
    def test_frozen_success_cannot_lose_third_or_projectile_proof(self):
        case=next(c for c in json.loads(FIXTURE.read_text())['cases'] if c['name']=='succeeded')
        for mutate in [lambda e:e['scoped_living_threats'].pop(),lambda e:e.pop('projectile_observation'),
                       lambda e:e['projectile_observation'].update(count=1)]:
            bad=copy.deepcopy(case['receipt']);mutate(bad['result']['combat']['encounter'])
            with self.assertRaises(ValueError):validate_encounter_receipt(bad,case['request'])
            with self.assertRaises(ValueError):harness_validate(bad,case['request'])

if __name__=='__main__':unittest.main()
