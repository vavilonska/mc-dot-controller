"""One existing owner/ledger for both contracts. Never manufacture migration authority."""
import os
from pathlib import Path
import stat
from urllib.parse import urlencode
from .legacy import legacy, Ledger, Refused, strict_json

NEW_PROFILE='recovery_interaction_v1'
NEW_ROOT='/control/recovery-interaction/v1/'


class JournalController(legacy.Controller):
    def __init__(self, directory, transport):
        directory=Path(directory)
        # Check before Ledger: its legacy constructor can initialize new storage;
        # this successor deliberately cannot use that capability.
        for filename in ('ledger.json','owner.json','owner.lock'):
            path=directory/filename
            if not path.exists() or path.is_symlink(): raise Refused('existing original ledger and owner are required')
        self.ledger=Ledger(directory)
        self.transport=transport
        self._last_observation=None
        try:
            data=self.ledger.data
            if data['endpoint'] != transport.endpoint or not data['actions']:
                raise Refused('original endpoint and nonempty history required')
            fd=os.open(directory/'owner.json',os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as stream:
                st=os.fstat(stream.fileno())
                if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o077:
                    raise Refused('original owner file must remain private')
                raw=stream.read(4097)
            if len(raw)>4096: raise Refused('owner file bound exceeded')
            owner=strict_json(raw)
            if not isinstance(owner,dict) or set(owner)!={'owner_id'}: raise Refused('original owner malformed')
            self.owner_id=owner['owner_id'];legacy.uuid(self.owner_id)
            for record in data['actions'].values():
                self.validate_request(record['request'])
                if record['request']['owner_id'] != self.owner_id: raise Refused('original owner mismatch')
                if record['state']=='CLOSED':
                    terminal=record.get('terminal_native')
                    self._validate_receipt(terminal,record['request'])
                    if terminal['state']!='SETTLED': raise Refused('original terminal missing')
        except BaseException:
            self.close()
            raise

    @staticmethod
    def validate_request(request):
        if request.get('profile')==legacy.PROFILE: return legacy.request_valid(request)
        raise Refused('unsupported original profile')

    @staticmethod
    def route(request):
        if request['profile']==legacy.PROFILE:return legacy.ROOT
        if request['profile']==NEW_PROFILE:return NEW_ROOT
        raise Refused('unsupported retained profile')

    def status(self,action_id):
        rec=self.ledger.data['actions'].get(action_id)
        if rec is None:raise Refused('unknown original ID')
        req=rec['request']
        query={key:req[key] for key in ('id','session','owner_id','owner_generation')}
        self._exchange(rec,'status','GET',self.route(req)+'status?'+urlencode(query))
        return self.report(action_id)

    def stop(self,action_id):
        rec=self.ledger.data['actions'].get(action_id)
        if rec is None:raise Refused('unknown original ID')
        if rec['stop_attempted']:return self.report(action_id)
        self._room(rec,1)
        req=rec['request']
        body={key:req[key] for key in ('schema_version','profile','id','session','owner_id','owner_generation')}
        rec['stop_attempted']=True
        self.ledger.save()
        self._exchange(rec,'stop','POST',self.route(req)+'stop',body)
        return self.report(action_id)
