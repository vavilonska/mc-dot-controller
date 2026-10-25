"""Read authorized journal-only fixture; write exclusively temporary clones."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from interaction_controller.legacy import strict_json, encode
from interaction_controller.journal import JournalController

FIXTURE=Path(__file__).resolve().parents[3]/'results'/'legacy57-fixtures'


@unittest.skipUnless((FIXTURE/'public-ledger.json').is_file(),'authorized 57-record journal fixture is not bundled here')
class RealLegacyTests(unittest.TestCase):
    def test_actual_57_exact_requests_digests_terminals_owner_and_evidence(self):
        ledger_raw=(FIXTURE/'public-ledger.json').read_bytes();owner_raw=(FIXTURE/'public-owner.json').read_bytes()
        original=strict_json(ledger_raw);owner=strict_json(owner_raw)
        self.assertEqual(len(original['actions']),57)
        class Offline:
            endpoint=original['endpoint']
            def request(self,*_):raise AssertionError('no native call permitted in fixture migration')
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'ledger';directory.mkdir(mode=0o700)
            for name,raw in (('ledger.json',ledger_raw),('owner.json',owner_raw)):
                (directory/name).write_bytes(raw);(directory/name).chmod(0o600)
            (directory/'owner.lock').touch(mode=0o600)
            with JournalController(directory,Offline()) as c:
                loaded=c.report();self.assertEqual(c.owner_id,owner['owner_id'])
                self.assertEqual(loaded,original)
                for aid,record in original['actions'].items():
                    for key in ('request','terminal_native','latest_native','evidence','state'):
                        self.assertEqual(loaded['actions'][aid][key],record[key])
                    self.assertEqual(loaded['actions'][aid]['terminal_native']['payload_digest'],record['terminal_native']['payload_digest'])
            self.assertEqual((directory/'owner.json').read_bytes(),owner_raw)
        self.assertEqual((FIXTURE/'public-ledger.json').read_bytes(),ledger_raw)
        self.assertEqual((FIXTURE/'public-owner.json').read_bytes(),owner_raw)

    def test_actual_57_prefix_survives_new_test_and_formal_intents_and_unknown_lock(self):
        from interaction_controller.controller import Controller
        from test_interaction import Fake,request,observation
        from uuid import uuid4
        from interaction_controller.legacy import Refused
        original=strict_json((FIXTURE/'public-ledger.json').read_bytes());owner=strict_json((FIXTURE/'public-owner.json').read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'ledger';directory.mkdir(mode=0o700)
            for name,raw in (('ledger.json',encode(original)),('owner.json',encode(owner))):
                (directory/name).write_bytes(raw);(directory/name).chmod(0o600)
            (directory/'owner.lock').touch(mode=0o600)
            transport=Fake();transport.obs['bound_owner_id']=owner['owner_id']
            for cell in transport.obs['local_blocks']:
                if cell['id']=='minecraft:cobblestone':cell.update(id='minecraft:air',collision=False)
            with Controller(directory,transport) as controller:
                for phase in ('TEST','FORMAL'):
                    transport.obs['world_generation']=str(uuid4());controller.observe()
                    req=request('move');req.update(owner_id=owner['owner_id'],world_generation=transport.obs['world_generation'],jump_first=True)
                    self.assertEqual(controller.start(req)['state'],'CLOSED')
                for aid,record in original['actions'].items():self.assertEqual(controller.report(aid),record)
                old_id=next(iter(original['actions']));controller.ledger.data['actions'][old_id]['state']='UNKNOWN';controller.ledger.data['unknown_lock']=True;controller.ledger.save()
                transport.obs['world_generation']=str(uuid4());controller.observe()
                req=request('move');req.update(owner_id=owner['owner_id'],world_generation=transport.obs['world_generation'],jump_first=True)
                with self.assertRaises(Refused):controller.start(req)
            self.assertEqual(len(transport.posts()),2)

if __name__=='__main__':unittest.main()
