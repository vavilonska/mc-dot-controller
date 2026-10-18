"""Read-only admission headroom. Never interrupts an admitted native action."""
from dataclasses import dataclass
from pathlib import Path
import os
from .contracts import ToolboxError

@dataclass(frozen=True)
class StorageReserve:
    warn_free_bytes: int = 1024*1024*1024
    min_free_bytes: int = 512*1024*1024
    event_history_admission_bytes: int = 64*1024*1024
    def __post_init__(self):
        values=(self.warn_free_bytes,self.min_free_bytes,self.event_history_admission_bytes)
        if any(type(v)is not int or not 1<=v<=2**53-1 for v in values) or self.warn_free_bytes<self.min_free_bytes:
            raise ValueError('invalid_storage_admission_thresholds')
    def snapshot(self,directory,event_bytes):
        value={'schema_version':1,'warn_free_bytes':self.warn_free_bytes,'min_free_bytes':self.min_free_bytes,
            'event_history_admission_bytes':self.event_history_admission_bytes,
            'event_history_bytes':event_bytes,'free_bytes':None,'status':'unknown','ordinary_mutation_admission':False,
            'read_status_reconcile_cancel_exempt':True,'existing_execution_not_interrupted':True,
            'capacity_is_admission_threshold_not_mid_action_hard_cap':True}
        try:
            if type(event_bytes)is not int or event_bytes<0:raise ValueError('invalid_event_accounting')
            stat=os.statvfs(Path(directory));free=stat.f_bavail*stat.f_frsize
            if type(free)is not int or free<0:raise ValueError('invalid_free_space')
            value['free_bytes']=free
            if free<self.min_free_bytes:value['status']='low_disk_reserve'
            elif event_bytes>=self.event_history_admission_bytes:value['status']='event_history_admission_full'
            else:value.update(status='warning'if free<self.warn_free_bytes else'ready',ordinary_mutation_admission=True)
        except (OSError,ValueError):value['status']='storage_probe_unavailable'
        return value
    def require(self,directory,event_bytes):
        state=self.snapshot(directory,event_bytes)
        if not state['ordinary_mutation_admission']:
            raise ToolboxError(state['status'],'New ordinary mutation refused by storage admission reserve; existing IDs and safety reads remain available',stage='storage_admission',suggested_next_operation='status')
        return state
