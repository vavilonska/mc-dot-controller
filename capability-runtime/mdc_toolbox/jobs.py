"""Durable single-owner job identity; restarts freeze, never replay, work."""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from .contracts import ToolboxError, json_data

class JobStore:
    MAX_JOBS=4096
    MAX_EVENTS=512
    def __init__(self,directory):
        path=Path(directory)
        path.mkdir(parents=True,exist_ok=True,mode=0o700)
        if path.is_symlink(): raise ToolboxError('journal_unavailable','Journal symlink prohibited',stage='storage')
        self._lock=threading.RLock(); self._closed=False
        self._fd=os.open(path/'toolbox.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(self._fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self._fd)
            raise ToolboxError('owner_busy','Another toolbox service owns this journal',stage='storage') from exc
        db_path=path/'jobs.sqlite3'
        fd=os.open(db_path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600); os.close(fd)
        self._db=sqlite3.connect(db_path,check_same_thread=False,isolation_level=None)
        self._db.execute('PRAGMA synchronous=FULL')
        self._db.execute('PRAGMA journal_mode=DELETE')
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(job_id TEXT NOT NULL, sequence INTEGER NOT NULL, event TEXT NOT NULL, PRIMARY KEY(job_id,sequence));
            CREATE TABLE IF NOT EXISTS cancellations(cancel_request_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, digest TEXT NOT NULL);
        ''')
        self.recover()

    @contextmanager
    def transaction(self):
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self._db.execute('COMMIT')
            except BaseException:
                self._db.execute('ROLLBACK'); raise

    def _write(self,record,event=None,payload=None):
        record=deepcopy(record)
        if event:
            current=self._db.execute('SELECT record FROM jobs WHERE job_id=?',(record['job_id'],)).fetchone()
            prior_cursor=json.loads(current[0]).get('event_cursor',0) if current else record.get('event_cursor',0)
            record['event_cursor']=prior_cursor+1
            value={'cursor':record['event_cursor'],'event':event,'at':time.time(),'payload':deepcopy(payload or {})}
            self._db.execute('INSERT INTO events VALUES(?,?,?)',(record['job_id'],value['cursor'],json_data(value).decode()))
            self._db.execute('DELETE FROM events WHERE job_id=? AND sequence<=?',(record['job_id'],value['cursor']-self.MAX_EVENTS))
        self._db.execute('INSERT INTO jobs VALUES(?,?,?) ON CONFLICT(job_id) DO UPDATE SET record=excluded.record',
                         (record['job_id'],record['request_id'],json_data(record).decode()))
        return record

    def save(self,record,event=None,payload=None):
        with self.transaction(): return self._write(record,event,payload)

    def create(self,record):
        with self.transaction():
            if self._db.execute('SELECT count(*) FROM jobs').fetchone()[0]>=self.MAX_JOBS:
                raise ToolboxError('journal_capacity_exhausted','Job identity retention limit reached',stage='storage')
            return self._write(record,'accepted',{'request_id':record['request_id']})

    def get(self,*,job_id=None,request_id=None):
        with self._lock:
            column,value=('job_id',job_id) if job_id is not None else ('request_id',request_id)
            row=self._db.execute(f'SELECT record FROM jobs WHERE {column}=?',(value,)).fetchone()
            return json.loads(row[0]) if row else None

    def all(self):
        with self._lock: return [json.loads(row[0]) for row in self._db.execute('SELECT record FROM jobs')]

    def event_page(self,job_id,cursor=0):
        with self._lock:
            all_rows=self._db.execute('SELECT sequence,event FROM events WHERE job_id=? ORDER BY sequence',(job_id,)).fetchall()
            gap=bool(all_rows and cursor<all_rows[0][0]-1)
            return [json.loads(row[1]) for row in all_rows if row[0]>cursor],gap

    def bind_cancel(self,cancel_id,job_id,digest):
        """Persist before the control call. Duplicate unknown cancellation is not replayed."""
        with self.transaction():
            row=self._db.execute('SELECT job_id,digest FROM cancellations WHERE cancel_request_id=?',(cancel_id,)).fetchone()
            if row:
                if row!=(job_id,digest): raise ToolboxError('request_conflict','Cancellation ID already binds different intent')
                return False
            self._db.execute('INSERT INTO cancellations VALUES(?,?,?)',(cancel_id,job_id,digest))
            return True

    def recover(self):
        for record in self.all():
            if record['state'] not in ('accepted','running','stopping'): continue
            if record.get('dispatch_started'):
                record.update(state='unknown',phase='restart_frozen',cleanup_certainty='unknown',continuation='reconcile_original_id_required')
                if record.get('effect_certainty')!='known': record['effect_certainty']='unknown'
            else:
                record.update(state='interrupted',phase='restart_frozen',effect_certainty='none_proven',cleanup_certainty='not_needed',continuation='fresh_replan_required')
            record['error']={'code':'interrupted','stage':'restart','reason':'Unfinished work frozen without dispatch or resume',
                             'effect_certainty':record['effect_certainty'],'affected_ids':record.get('request_ids',[]),'suggested_next_operation':'reconcile'}
            self.save(record,'restart_frozen')

    def close(self):
        with self._lock:
            if self._closed:return
            self._db.close(); fcntl.flock(self._fd,fcntl.LOCK_UN); os.close(self._fd); self._closed=True
