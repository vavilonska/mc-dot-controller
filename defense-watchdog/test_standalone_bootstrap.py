"""Actual delivered entrypoints in isolated environments; no game or network."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

SOURCE = Path(os.environ.get('MDC_BOOTSTRAP_SOURCE', Path(__file__).resolve().parents[1])).resolve()
PYTHON = str(Path(sys.executable).resolve())
NODE = shutil.which('node')


def environment(home):
    return {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': str(home),
            'XDG_CONFIG_HOME': str(home), 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value))
    tmp.replace(path)


class StandaloneBootstrap(unittest.TestCase):
    def test_missing_dependency_fails_and_both_delivered_layouts_resolve(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);package=root/'resident-controller/resident_controller';package.mkdir(parents=True)
            helper=package/'runtime_paths.py';shutil.copyfile(SOURCE/'resident-controller/resident_controller/runtime_paths.py',helper)
            code='import runpy,sys;ns=runpy.run_path(sys.argv[1]);print(ns["configure_source_dependencies"]())'
            p=subprocess.run([PYTHON,'-B','-c',code,str(helper)],cwd=t,env=environment(t),capture_output=True,text=True,timeout=5)
            self.assertNotEqual(p.returncode,0);self.assertIn('delivered_navigation_controller_dependency_missing',p.stderr)
            for name in ('navigation-controller','minecraft-navigation-controller'):
                with self.subTest(layout=name):
                    target=root/name/'navigation_controller';target.mkdir(parents=True);(target/'observation_clock.py').write_text('# offline package marker\n')
                    p=subprocess.run([PYTHON,'-B','-c',code,str(helper)],cwd=t,env=environment(t),capture_output=True,text=True,timeout=5)
                    self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),str(root/name))
                    (target/'observation_clock.py').unlink();target.rmdir();target.parent.rmdir()

    def test_standalone_import_graph_uses_delivered_siblings(self):
        code = '''import sys,json
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'defense-watchdog'))
import watchdog,reconciliation_read,managed_navigation_owner,external_navigation_owner
from resident_controller import compact_observation,reconciliation_read as resident_read
from resident_controller import managed_navigation_control,external_navigation_control,combat_snapshot
import navigation_controller.observation_clock as clock
assert Path(clock.__file__).resolve().is_relative_to(root/'navigation-controller')
print('DELIVERED_IMPORT_GRAPH_OK')'''
        with tempfile.TemporaryDirectory() as t:
            p=subprocess.run([PYTHON,'-B','-c',code,str(SOURCE)],cwd=t,env=environment(t),capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr);self.assertIn('DELIVERED_IMPORT_GRAPH_OK',p.stdout)

    def test_resident_canonical_module_entrypoint_without_ambient_siblings(self):
        with tempfile.TemporaryDirectory() as t:
            env=environment(t);env['PYTHONPATH']=str(SOURCE/'resident-controller')
            p=subprocess.run([PYTHON,'-B','-m','resident_controller','--help'],cwd=t,env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr);self.assertIn('start',p.stdout)
            code='import resident_controller.__main__;from resident_controller import compact_observation,reconciliation_read,managed_navigation_control,combat_snapshot;print("RESIDENT_DEPENDENCIES_OK")'
            p=subprocess.run([PYTHON,'-B','-c',code],cwd=t,env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr);self.assertIn('RESIDENT_DEPENDENCIES_OK',p.stdout)

    def test_delivered_watchdog_run_and_stop_with_only_offline_mailbox(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);queue=root/'resident';control=root/'watchdog'
            atomic(queue/'session.json',{'session_id':'offline-startup-smoke','state':'ready'})
            command=[PYTHON,'-B',str(SOURCE/'defense-watchdog/watchdog.py'),'run','--queue',str(queue),'--control',str(control),'--execution-policy','request_only']
            with (root/'stderr').open('w+') as log:
                p=subprocess.Popen(command,cwd=root,env=environment(root),stdin=subprocess.DEVNULL,stdout=log,stderr=log)
                try:
                    until=time.monotonic()+8
                    while not (control/'state.json').exists() and p.poll() is None and time.monotonic()<until:time.sleep(.02)
                    log.flush();self.assertIsNone(p.poll(),(root/'stderr').read_text())
                    state=json.loads((control/'state.json').read_text());self.assertEqual(state['execution_policy'],'request_only')
                    self.assertEqual(state['implementation'],'native-defense-watchdog-v5')
                    (control/'STOP').write_text('offline-test-only\n')
                    seen=[]
                    while p.poll() is None and time.monotonic()<until:
                        for request in (queue/'inbox').glob('*.json'):
                            body=json.loads(request.read_text());self.assertIn(body['op'],('observe','cancel'));seen.append(body['op'])
                            if body['op']=='cancel':atomic(queue/'results'/request.name,{'request_id':body['request_id'],'session_id':body['session_id'],'status':'succeeded','result':{'ok':True}})
                        time.sleep(.02)
                    self.assertEqual(p.wait(timeout=2),0,(root/'stderr').read_text())
                    self.assertIn('cancel',seen);state=json.loads((control/'state.json').read_text());self.assertTrue(state['stopped'])
                    self.assertFalse(any('ModuleNotFoundError' in line for line in (root/'stderr').read_text().splitlines()))
                finally:
                    if p.poll() is None:p.terminate();p.wait(timeout=3)

    @unittest.skipUnless(NODE,'Node executable is required for the public startup gate')
    def test_real_public_node_catalog_starts_python_with_clean_parent_environment(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);control=root/'control';control.mkdir(mode=0o700)
            atomic(control/'state.json',{'implementation':'native-defense-watchdog-v5','session_id':'offline-gateway','state':'ready','pending':0,'updated_at':time.time()})
            config=root/'config.json';atomic(config,{'schema_version':1,'python_executable':PYTHON,'python_sha256':hashlib.sha256(Path(PYTHON).read_bytes()).hexdigest(),'control_directory':str(control),'journal_directory':str(root/'journal'),'runtime_journal_directory':str(root/'runtime')});config.chmod(0o600)
            env=environment(root);env['MINECLIENT_TOOLBOX_CONFIG']=str(config)
            with (root/'stderr').open('w+') as log:
                p=subprocess.Popen([NODE,str(SOURCE/'client-mod/mcp/mineclient-bridge-mcp.mjs')],cwd=root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,bufsize=1)
                selector=selectors.DefaultSelector();selector.register(p.stdout,selectors.EVENT_READ)
                def rpc(identity,method,params):
                    p.stdin.write(json.dumps({'jsonrpc':'2.0','id':identity,'method':method,'params':params})+'\n');p.stdin.flush()
                    self.assertTrue(selector.select(10),(root/'stderr').read_text());reply=json.loads(p.stdout.readline());self.assertEqual(reply.get('id'),identity);self.assertNotIn('error',reply);return reply['result']
                try:
                    rpc('init','initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'offline-bootstrap','version':'1'}})
                    listed=rpc('list','tools/list',{});self.assertIn('mdc_catalog',{x['name'] for x in listed['tools']})
                    result=rpc('catalog','tools/call',{'name':'mdc_catalog','arguments':{'api_version':'mdc.toolbox/1','detail':'contracts','limit':128}})
                    payload=result.get('structuredContent') or json.loads(result['content'][0]['text'])
                    self.assertNotIn('error',payload);self.assertEqual(payload['api_version'],'mdc.toolbox/1')
                    ids={x['capability'] for x in payload['capabilities']};self.assertTrue({'defend_local','navigate_managed_walk','fall_rescue_guard'}<=ids)
                    self.assertTrue((root/'runtime').is_dir(),'Configured Python backend was not started')
                    self.assertFalse((control/'inbox').exists(),'Catalog must not dispatch an intent')
                    p.stdin.close();self.assertEqual(p.wait(timeout=10),0,(root/'stderr').read_text())
                finally:
                    selector.close()
                    if p.poll() is None:p.terminate();p.wait(timeout=3)
                    p.stdout.close()


if __name__=='__main__':unittest.main()
