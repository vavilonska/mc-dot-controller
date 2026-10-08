"""QueueClient-shaped gateway client. It never writes to the resident mailbox."""
import json
from pathlib import Path
import re
import time
import uuid
from watchdog import OWNER_OPS, write_json
from base_watchdog import recovery_close_command
ID = re.compile(r'[A-Za-z0-9_-]{1,80}')

class IntentClient:
    def __init__(self, directory):
        self.root = Path(directory)
    def session(self):
        data = json.loads((self.root/'state.json').read_text())
        if data.get('implementation') != 'native-defense-watchdog-v5':
            raise ValueError('watchdog_v5_required')
        if time.time() - data.get('updated_at', 0) > 3:
            raise ValueError('watchdog_heartbeat_stale')
        return data
    def submit(self, command, request_id=None):
        session = self.session()
        recovery_close = (session.get('state') == 'paused'
                          and session.get('menu_recovery', {}).get('can_close') is True
                          and recovery_close_command(command))
        if (session.get('state') not in ('ready', 'busy') and not recovery_close) or (self.root/'STOP').exists():
            raise ValueError('watchdog_not_accepting_intents')
        if not isinstance(command, dict) or command.get('op') not in OWNER_OPS:
            raise ValueError('unsupported_owner_intent')
        request_id = request_id or uuid.uuid4().hex
        if not ID.fullmatch(request_id):
            raise ValueError('invalid_request_id')
        name = request_id+'.json'
        for folder in ('inbox','working','results'):
            if (self.root/folder/name).exists():return request_id
        if len(list((self.root/'inbox').glob('*.json'))) >= 1:
            raise ValueError('one_pending_owner_intent_only')
        body = {**command, '_watchdog_session_id': session['session_id']}
        if len(json.dumps(body).encode()) > 64*1024:
            raise ValueError('intent_too_large')
        write_json(self.root/'inbox'/name,body)
        return request_id
    def result(self, request_id):
        if not ID.fullmatch(request_id):raise ValueError('invalid_request_id')
        path=self.root/'results'/(request_id+'.json')
        if not path.exists():return None
        wrapped=json.loads(path.read_text())
        if 'intent_id' not in wrapped:
            return wrapped  # Explicit restart/stale-intent result.
        original=wrapped['result']
        return {**original, 'request_id':request_id, 'session_id':wrapped['session_id'],
                'queue_request_id':wrapped['queue_request_id'],
                'queue_session_id':original.get('session_id')}
    def wait(self, request_id, timeout=30):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            result=self.result(request_id)
            if result is not None:return result
            time.sleep(.1)
        return {'request_id':request_id,'status':'pending','reason':'wait_timeout_not_action_failure'}
