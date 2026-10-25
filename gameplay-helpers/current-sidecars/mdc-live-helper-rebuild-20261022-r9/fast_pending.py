"""Sidecar preparation of CLOSED history, never a journal or durability shortcut.

Call prepare() before the final fresh observation, then use save_pending exactly
once. Only the new record is encoded after that observation. The final complete
PENDING ledger still follows C8's original atomic write/fsync/replace/dir-fsync
sequence and returns its original single-use _StartCapacityProof.

As in C8 storage, this requires one cooperating controller thread. Completed
controller mutations call ledger.save() and invalidate _save_epoch. The cache
pins epoch, containers, record identities and a deep header snapshot; it does
not claim to detect unsupported bare in-place edits of nested CLOSED records
without save(), or provide thread-safe/reentrant mutation support.
"""
import copy
import os
import tempfile

from survival6_controller.legacy import Refused, encode
from survival6_controller.storage import CLEANUP_RESERVE, _StartCapacityProof


class PreparedHistory:
    def __init__(self, ledger):
        self.ledger = ledger
        self._prepared = None
        self._original = ledger._save_pending

    def install(self):
        """Bind only this ledger instance; no frozen production source changes."""
        current = self.ledger._save_pending
        if current != self._original and current != self.save_pending:
            raise Refused('different pending adapter already installed')
        self.ledger._save_pending = self.save_pending
        return self

    def _unchanged(self, prepared, epoch):
        ledger = self.ledger
        if (prepared is None or ledger._save_epoch != epoch
                or ledger.data is not prepared['data']
                or ledger.data.get('actions') is not prepared['actions']):
            return False
        data, actions = ledger.data, prepared['actions']
        return (data.get('unknown_lock') is False
                and {k: v for k, v in data.items() if k != 'actions'} == prepared['header']
                and len(actions) == len(prepared['records'])
                and all(actions.get(k) is record and record.get('state') == 'CLOSED'
                        for k, record in prepared['records']))

    def prepare(self):
        """Prepare before fresh; an unchanged unconsumed preparation may be reused."""
        if self._prepared is not None and self._unchanged(self._prepared, self._prepared['epoch']):
            return self
        self._prepared = None
        ledger = self.ledger
        data = ledger.data
        actions = data.get('actions')
        if (not isinstance(actions, dict) or data.get('unknown_lock') is not False
                or any(not isinstance(record, dict) or record.get('state') != 'CLOSED'
                       for record in actions.values())
                or any(not isinstance(k, str) for k in data)
                or any(not isinstance(k, str) for k in actions)):
            raise Refused('only known CLOSED history can be prepared')
        prepared = dict(epoch=ledger._save_epoch, data=data, actions=actions,
                        records=tuple(actions.items()),
                        header=copy.deepcopy({k: v for k, v in data.items() if k != 'actions'}))
        # Same sort_keys/escaping/scalar codec as encode(prospective); no new
        # action, cursor, serial or ledger mutation happens during preparation.
        prepared['fragments'] = tuple((key, encode(key) + b':' + encode(actions[key]))
                                      for key in sorted(actions))
        before, after = [], []
        for key in sorted(prepared['header']):
            pair = encode(key) + b':' + encode(prepared['header'][key])
            (before if key < 'actions' else after).append(pair)
        prepared['prefix'] = b'{' + b','.join(before + [b'"actions":{'])
        prepared['suffix'] = b'}' + (b',' + b','.join(after) if after else b'') + b'}'
        if not self._unchanged(prepared, prepared['epoch']):
            raise Refused('history changed during preparation; no dispatch')
        self._prepared = prepared
        return self

    @staticmethod
    def _assemble(prepared, action_id, rec):
        new = encode(action_id) + b':' + encode(rec)
        pieces = [prepared['prefix']]
        first, inserted = True, False
        for key, raw in prepared['fragments']:
            if not inserted and action_id < key:
                if not first:
                    pieces.append(b',')
                pieces.append(new)
                first, inserted = False, True
            if not first:
                pieces.append(b',')
            pieces.append(raw)
            first = False
        if not inserted:
            if not first:
                pieces.append(b',')
            pieces.append(new)
        pieces.append(prepared['suffix'])
        return b''.join(pieces)

    def save_pending(self, rec, max_actions):
        """Consume one preparation; refuse stale state, never fallback to full encode."""
        prepared, self._prepared = self._prepared, None
        ledger = self.ledger
        # Preserve C8's failed-attempt epoch invalidation as well as one-use cache.
        previous_epoch = ledger._save_epoch
        ledger._save_epoch += 1
        if (prepared is None or prepared['epoch'] != previous_epoch
                or not self._unchanged(prepared, previous_epoch + 1)):
            raise Refused('missing or stale prepared history; no dispatch')
        data, actions = ledger.data, ledger.data['actions']
        if len(actions) >= max_actions:
            raise Refused('V6 action count ceiling reached; no dispatch')
        action_id = rec['request']['id']
        if action_id in actions:
            raise Refused('original action already retained; no dispatch')
        if not isinstance(action_id, str):
            raise Refused('canonical string action ID required; no dispatch')
        raw = self._assemble(prepared, action_id, rec)
        if len(raw) + CLEANUP_RESERVE > ledger.MAX_BYTES:
            raise Refused('byte ceiling prevents new intent; original evidence retained')
        # Identical to original _save_pending from this point: full actual bytes
        # are admitted, and a failed write never makes this action appear new.
        actions[action_id] = rec
        epoch, snapshot = ledger._save_epoch, copy.deepcopy(rec)
        records = tuple(actions.items())
        header = {k: v for k, v in data.items() if k != 'actions'}
        fd, temp = tempfile.mkstemp(prefix='.ledger-', dir=ledger.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                if stream.write(raw) != len(raw):
                    raise OSError('incomplete ledger write')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, ledger.path)
            dfd = os.open(ledger.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except BaseException:
            ledger._save_epoch += 1
            raise
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        if (ledger._save_epoch != epoch or ledger.data is not data or data['actions'] is not actions
                or rec != snapshot or len(actions) != len(records)
                or any(actions.get(k) is not v for k, v in records)
                or {k: v for k, v in data.items() if k != 'actions'} != header):
            raise Refused('ledger changed during pending persistence; no dispatch')
        return _StartCapacityProof(ledger, rec, len(raw))
