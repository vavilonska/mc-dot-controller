"""V6-only capacity and a same-start, single-consumption durable capacity proof.

One cooperating controller thread, as in the original Ledger. There is no size
cache or proof across calls. Every ordinary save still encodes the whole ledger.
"""
import copy
import os
import tempfile
from .legacy import MaintenanceLedger, Refused, MAX_RESPONSE, encode

CLEANUP_RESERVE = MAX_RESPONSE * 2 * 3


class _StartCapacityProof:
    def __init__(self, ledger, rec, raw_size):
        self.ledger = ledger
        self.epoch = ledger._save_epoch
        self.data = ledger.data
        self.actions = ledger.data['actions']
        self.records = tuple(self.actions.items())
        self.header = {k: v for k, v in self.data.items() if k != 'actions'}
        self.rec = rec
        self.snapshot = copy.deepcopy(rec)
        self.raw_size = raw_size
        self.used = False

    def consume(self, ledger, rec):
        # Mark consumed before validation: an invalid proof cannot later recover.
        used, self.used = self.used, True
        if (used or ledger is not self.ledger or ledger._save_epoch != self.epoch
                or ledger.data is not self.data or self.data['actions'] is not self.actions
                or rec is not self.rec or rec != self.snapshot
                or {k: v for k, v in self.data.items() if k != 'actions'} != self.header
                or len(self.actions) != len(self.records)
                or any(self.actions.get(k) is not v for k, v in self.records)
                or self.actions.get(rec['request']['id']) is not rec
                or rec['state'] != 'PENDING' or rec['evidence'] or rec['stop_attempted']
                or self.raw_size + CLEANUP_RESERVE > ledger.MAX_BYTES):
            raise Refused('invalid same-start capacity proof; no dispatch')


class SurvivalLedger(MaintenanceLedger):
    MAX_BYTES = 128 * 1024 * 1024
    MAX_ACTIONS = 4096

    def __init__(self, directory):
        self._save_epoch = 0
        super().__init__(directory)

    def save(self):
        # Failed attempts also invalidate a pending proof. Retain original codec
        # and durability path for receipts, status, stop and restart conversion.
        self._save_epoch += 1
        if len(self.data['actions']) > self.MAX_ACTIONS:
            raise Refused('V6 retained action count ceiling exceeded; preserve ledger')
        return super().save()

    def _save_pending(self, rec, max_actions):
        self._save_epoch += 1
        if len(self.data['actions']) >= max_actions:
            raise Refused('V6 action count ceiling reached; no dispatch')
        data, actions = self.data, self.data['actions']
        action_id = rec['request']['id']
        if action_id in actions:raise Refused('original action already retained; no dispatch')
        prospective = dict(data, actions=dict(actions, **{action_id: rec}))
        raw = encode(prospective)  # The one final, actual PENDING encoding.
        if len(raw) + CLEANUP_RESERVE > self.MAX_BYTES:
            raise Refused('byte ceiling prevents new intent; original evidence retained')
        # Capacity/codec rejection does not mutate history. Once writing begins,
        # retain PENDING in memory even on failure: never make retry look new.
        actions[action_id] = rec
        epoch, snapshot = self._save_epoch, copy.deepcopy(rec)
        records = tuple(actions.items())
        header = {k: v for k, v in data.items() if k != 'actions'}
        # Same atomic sequence as the original Ledger.save, with the exact bytes
        # used for capacity admission; no encode or serializer between here/POST.
        fd, temp = tempfile.mkstemp(prefix='.ledger-', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                if stream.write(raw) != len(raw):
                    raise OSError('incomplete ledger write')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
            dfd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except BaseException:
            self._save_epoch += 1
            raise
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        if (self._save_epoch != epoch or self.data is not data or data['actions'] is not actions
                or rec != snapshot or len(actions) != len(records)
                or any(actions.get(k) is not v for k, v in records)
                or {k: v for k, v in data.items() if k != 'actions'} != header):
            raise Refused('ledger changed during pending persistence; no dispatch')
        return _StartCapacityProof(self, rec, len(raw))
