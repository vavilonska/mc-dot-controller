"""Focused offline faults; all writes are private TEMP clones and HTTP is fake."""
import copy, os, stat, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from fixtures import *
from survival6_controller import storage
from survival6_controller.legacy import Refused, MaintenanceLedger
from short_input_controller.storage import Ledger

ONE = dict(BASE, actions={LAST['request']['id']: copy.deepcopy(LAST)})

class Capacity(unittest.TestCase):
 def setup(self,t):
  d=Path(t)/'ledger';clone(d,encode(ONE));f=Fake();p=plan();c=Controller(d,f,p);c.observe();return d,f,p,c,request('consume_bread',p)
 def test_v6_limits_do_not_modify_historical_classes(self):
  self.assertEqual(Controller.MAX_ACTIONS,4096);self.assertEqual(storage.SurvivalLedger.MAX_BYTES,128*1024*1024)
  self.assertEqual(MaintenanceLedger.MAX_BYTES,24*1024*1024);self.assertEqual(Ledger.MAX_BYTES,8*1024*1024)
  self.assertEqual(__import__('navigation5_controller').Controller.MAX_ACTIONS,512)
 def test_ledger_read_count4096_accepts_count4097_refuses_without_rewrite(self):
  for count in (4096,4097):
   with self.subTest(count=count),tempfile.TemporaryDirectory()as t:
    data=dict(ONE,actions={})
    for i in range(count):
     aid=str(uuid4());data['actions'][aid]=dict(request={'id':aid},state='CLOSED',evidence=[],unknown_reasons=[],stop_attempted=False)
    d=Path(t)/'ledger';raw=encode(data);clone(d,raw)
    if count==4096:
     with storage.SurvivalLedger(d)as ledger:self.assertEqual(len(ledger.data['actions']),4096)
    else:
     with self.assertRaises(Refused):storage.SurvivalLedger(d)
    self.assertEqual((d/'ledger.json').read_bytes(),raw)
 def test_4096th_storage_intent_and_4097th_start_refusal(self):
  # Deliberately minimal storage-schema records isolate count from byte limits;
  # real996 below separately exercises all original request/receipt readers.
  with tempfile.TemporaryDirectory()as t:
   d,f,p,c,q=self.setup(t)
   try:
    for i in range(4095-len(c.ledger.data['actions'])):
     aid=str(uuid4());c.ledger.data['actions'][aid]=dict(request={'id':aid},state='CLOSED',evidence=[],unknown_reasons=[],stop_attempted=False)
    rec=dict(request=q,state='PENDING',evidence=[],unknown_reasons=[],stop_attempted=False)
    proof=c.ledger._save_pending(rec,c.MAX_ACTIONS);proof.consume(c.ledger,rec)
    self.assertEqual(len(c.ledger.data['actions']),4096);rec['state']='CLOSED';c.ledger.save()
    q2=dict(q,id=str(uuid4()));before=(d/'ledger.json').read_bytes()
    with self.assertRaisesRegex(Refused,'shared4096'):c.start(q2)
    self.assertEqual(f.starts(),[]);self.assertNotIn(q2['id'],c.ledger.data['actions']);self.assertEqual((d/'ledger.json').read_bytes(),before)
    with self.assertRaisesRegex(Refused,'count ceiling'):c.ledger._save_pending(dict(rec,request=q2),c.MAX_ACTIONS)
   finally:c.close()
 def test_actual128mib_final_pending_plus_reserve_exact_and_one_byte_over(self):
  # Single boundary regression, not a throughput/load benchmark. Real production
  # start/gate/persistence, tiny historical fixture plus explicit test padding.
  for over in (0,1):
   with self.subTest(one_byte_over=over),tempfile.TemporaryDirectory()as t:
    d,f,p,c,q=self.setup(t);captured=[]
    def capture(rec,limit):captured.append(copy.deepcopy(rec));raise Refused('capture final pending')
    try:
     with patch.object(c.ledger,'_save_pending',side_effect=capture),self.assertRaises(Refused):c.start(q)
     old=next(iter(c.ledger.data['actions'].values()));old['test_capacity_padding']=''
     prospective=dict(c.ledger.data,actions=dict(c.ledger.data['actions'],**{q['id']:captured[0]}))
     empty_size=len(encode(prospective));target=c.ledger.MAX_BYTES-storage.CLEANUP_RESERVE+over
     old['test_capacity_padding']='x'*(target-empty_size);before=(d/'ledger.json').read_bytes()
     if over:
      with self.assertRaises(Refused):c.start(q)
      self.assertNotIn(q['id'],c.ledger.data['actions']);self.assertEqual(f.starts(),[]);self.assertEqual((d/'ledger.json').read_bytes(),before)
     else:
      def before_post(m,path,body):
       if path.endswith('start'):self.assertEqual((d/'ledger.json').stat().st_size,target)
      f.before=before_post;c.start(q);self.assertEqual(len(f.starts()),1);self.assertEqual(c.report(q['id'])['state'],'CLOSED')
     self.assertEqual(c.ledger.MAX_BYTES,128*1024*1024)
    finally:c.close()
 def test_actual996_original_retrieval_and_historical_unsettled_lock(self):
  frozen=C.parent/'mdc-runtime-recovery-20261021-r1/nether-north-996-nine-stage-cold-frozen-r1/public-ledger-996.json'
  raw=frozen.read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),'7adf0f5e0882210cc18f21dd5b4b36efe366a0c94a090d15ffb82abd8a259fa9')
  original=strict_json(raw);self.assertEqual(len(original['actions']),996)
  known_zero=[r for r in original['actions'].values()if r['state']=='CLOSED'and r['terminal_native'].get('applied_calls',r['terminal_native'].get('applied_samples',-1))==0]
  self.assertEqual(len(known_zero),5)
  for state in ('CLOSED','UNKNOWN','PENDING'):
   with self.subTest(state=state),tempfile.TemporaryDirectory()as t:
    data=copy.deepcopy(original);aid=next(k for k,r in data['actions'].items()if r['request']['profile']!=PROFILE)
    data['actions'][aid]['state']=state;data['unknown_lock']=state=='UNKNOWN';d=Path(t)/'ledger';clone(d,encode(data));f=Fake();p=plan();c=Controller(d,f,p)
    try:
     for k,r in original['actions'].items():
      if k!=aid or state=='CLOSED':self.assertEqual(encode(c.start(r['request'])),encode(r))
     self.assertEqual(f.calls,[])
     for r in known_zero:
      if r['request']['id']!=aid or state=='CLOSED':self.assertEqual(encode(c.start(r['request'])),encode(r))
     self.assertEqual(f.starts(),[])
     if state!='CLOSED':
      retained=c.report(aid);self.assertEqual(retained['state'],'UNKNOWN');self.assertTrue(c.ledger.data['unknown_lock'])
      for field in ('request','evidence','latest_native','terminal_native','plan','observation'):self.assertEqual(encode(retained.get(field)),encode(original['actions'][aid].get(field)))
      c.observe()
      with self.assertRaises(Refused):c.start(request('consume_bread',p))
      self.assertEqual(f.starts(),[])
    finally:c.close()
  self.assertEqual(hashlib.sha256(frozen.read_bytes()).hexdigest(),'7adf0f5e0882210cc18f21dd5b4b36efe366a0c94a090d15ffb82abd8a259fa9')
 def test_exact_encoded_bytes_single_prepost_encode_and_durable_order(self):
  with tempfile.TemporaryDirectory()as t:
   d,f,p,c,q=self.setup(t);encoded=[];events=[];fsync=os.fsync;replace=os.replace
   def codec(data):raw=encode(data);encoded.append(raw);return raw
   def sync(fd):events.append('dirfsync'if stat.S_ISDIR(os.fstat(fd).st_mode)else'filefsync');return fsync(fd)
   def repl(a,b):events.append('replace');return replace(a,b)
   def before(m,path,b):
    if path.endswith('start'):
     self.assertEqual(events,['filefsync','replace','dirfsync']);self.assertEqual(len(encoded),1)
     self.assertEqual((d/'ledger.json').read_bytes(),encoded[0]);self.assertEqual(strict_json(encoded[0])['actions'][q['id']]['state'],'PENDING');self.assertIsNone(c._start_capacity_proof)
   f.before=before
   try:
    with patch.object(storage,'encode',side_effect=codec),patch.object(storage.os,'fsync',side_effect=sync),patch.object(storage.os,'replace',side_effect=repl):c.start(q)
    self.assertEqual(c.report(q['id'])['state'],'CLOSED');self.assertEqual(len(f.starts()),1)
   finally:c.close()
 def test_final_byte_plus_reserve_boundary_and_count_boundary(self):
  # Capture exact prospective bytes then test exact/+1 capacity without dispatch.
  for delta in (0,-1):
   with self.subTest(delta=delta),tempfile.TemporaryDirectory()as t:
    d,f,p,c,q=self.setup(t);old=(d/'ledger.json').read_bytes();real=storage.encode
    def bounded(data):
     raw=real(data);c.ledger.MAX_BYTES=len(raw)+storage.CLEANUP_RESERVE+delta;return raw
    try:
     with patch.object(storage,'encode',side_effect=bounded):
      if delta<0:
       with self.assertRaises(Refused):c.start(q)
       self.assertNotIn(q['id'],c.ledger.data['actions']);self.assertEqual((d/'ledger.json').read_bytes(),old);self.assertEqual(f.starts(),[])
      else:c.start(q);self.assertEqual(len(f.starts()),1)
    finally:c.close()
 def test_encode_and_all_durability_failures_zero_post(self):
  for failure in ('encode','mkstemp','write','shortwrite','flush','filefsync','replace','dirfsync'):
   with self.subTest(failure=failure),tempfile.TemporaryDirectory()as t:
    d,f,p,c,q=self.setup(t);old=(d/'ledger.json').read_bytes();fsync=os.fsync;fdopen=os.fdopen
    def sync(fd):
     kind='dirfsync'if stat.S_ISDIR(os.fstat(fd).st_mode)else'filefsync'
     if kind==failure:raise OSError('injected '+kind)
     return fsync(fd)
    class BadWrite:
     def __init__(self,s):self.s=s
     def __enter__(self):return self
     def __exit__(self,*args):self.s.close()
     def write(self,raw):
      if failure=='write':raise OSError('injected write')
      if failure=='shortwrite':return len(raw)-1
      return self.s.write(raw)
     def flush(self):raise OSError('injected flush')
    def opened(fd,mode):return BadWrite(fdopen(fd,mode))
    target,obj,kw=(storage,'encode',{'side_effect':ValueError('injected encode')})if failure=='encode'else(storage.tempfile,'mkstemp',{'side_effect':OSError('injected mkstemp')})if failure=='mkstemp'else(storage.os,'fdopen',{'side_effect':opened})if failure in('write','shortwrite','flush')else(storage.os,'replace',{'side_effect':OSError('injected replace')})if failure=='replace'else(storage.os,'fsync',{'side_effect':sync})
    try:
     with patch.object(target,obj,**kw),self.assertRaises((OSError,ValueError)):c.start(q)
     self.assertEqual(f.starts(),[]);self.assertIsNone(c._start_capacity_proof)
     if failure=='encode':self.assertNotIn(q['id'],c.ledger.data['actions'])
     else:
      self.assertEqual(c.report(q['id'])['state'],'PENDING');c.start(q);self.assertEqual(f.starts(),[])
     if failure!='dirfsync':self.assertEqual((d/'ledger.json').read_bytes(),old)
     else:self.assertEqual(strict_json((d/'ledger.json').read_bytes())['actions'][q['id']]['state'],'PENDING')
    finally:c.close()
 def test_invalid_stale_mutated_used_and_cross_action_proof_zero_post(self):
  for failure in ('save','failedsave','mutation','header','newrecord','badkind','used','other'):
   with self.subTest(failure=failure),tempfile.TemporaryDirectory()as t:
    d,f,p,c,q=self.setup(t);saved=c._exchange;proofs=[]
    def intercept(rec,kind,method,path,body=None,*,_capacity_proof=None):
     proof=_capacity_proof;proofs.append(proof)
     if failure=='save':c.ledger.save()
     elif failure=='failedsave':
      with patch('short_input_controller.storage.encode',side_effect=ValueError('failed save')):
       with self.assertRaises(ValueError):c.ledger.save()
     elif failure=='mutation':rec['stop_attempted']=True
     elif failure=='header':c.ledger.data['unknown_lock']=True
     elif failure=='newrecord':c.ledger.data['actions']['new']=copy.deepcopy(rec)
     elif failure=='badkind':kind='status'
     elif failure=='used':proof.consume(c.ledger,rec)
     elif failure=='other':rec=copy.deepcopy(rec)
     return saved(rec,kind,method,path,body,_capacity_proof=proof)
    try:
     with patch.object(c,'_exchange',side_effect=intercept),self.assertRaises(Refused):c.start(q)
     self.assertEqual(f.starts(),[]);self.assertIsNone(c._start_capacity_proof);self.assertTrue(proofs[0].used)
    finally:c.close()
 def test_mutation_or_save_during_persistence_cannot_create_proof(self):
  for change in ('record','header','save'):
   with self.subTest(change=change),tempfile.TemporaryDirectory()as t:
    d,f,p,c,q=self.setup(t);fsync=os.fsync;changed=[]
    def sync(fd):
     fsync(fd)
     if stat.S_ISDIR(os.fstat(fd).st_mode)and not changed:
      changed.append(True)
      if change=='record':c.ledger.data['actions'][q['id']]['stop_attempted']=True
      elif change=='header':c.ledger.data['unknown_lock']=True
      else:c.ledger.save()
    try:
     with patch.object(storage.os,'fsync',side_effect=sync),self.assertRaises(Refused):c.start(q)
     self.assertEqual(f.starts(),[]);self.assertIsNone(c._start_capacity_proof);self.assertEqual(c.report(q['id'])['state'],'PENDING')
    finally:c.close()
 def test_raw_receipt_save_and_status_stop_do_not_use_start_proof(self):
  with tempfile.TemporaryDirectory()as t:
   d,f,p,c,q=self.setup(t);proofs=[];pending=c.ledger._save_pending
   def capture(*a):proof=pending(*a);proofs.append(proof);return proof
   try:
    with patch.object(c.ledger,'_save_pending',side_effect=capture),patch('short_input_controller.storage.encode',side_effect=ValueError('receipt codec failed')):
     with self.assertRaises(ValueError):c.start(q)
    self.assertEqual(len(f.starts()),1);self.assertTrue(proofs[0].used);self.assertIsNone(c._start_capacity_proof)
    self.assertGreater(c.ledger._save_epoch,proofs[0].epoch);self.assertEqual(len(c.report(q['id'])['evidence']),1)
    before=len(f.calls)
    with patch('short_input_controller.controller.encode',side_effect=Refused('fresh capacity check required')):
     with self.assertRaises(Refused):c.status(q['id'])
     with self.assertRaises(Refused):c.stop(q['id'])
    self.assertEqual(len(f.calls),before);self.assertFalse(c.report(q['id'])['stop_attempted'])
    c.stop(q['id']);c.status(q['id']);self.assertEqual(len(f.starts()),1);self.assertEqual(len(f.stops()),1)
   finally:c.close()
 def test_transport_throw_unknown_original_id_cleanup_and_no_proof_reuse(self):
  with tempfile.TemporaryDirectory()as t:
   d,f,p,c,q=self.setup(t);proofs=[];pending=c.ledger._save_pending
   def capture(*a):proof=pending(*a);proofs.append(proof);return proof
   def before(m,path,b):
    if path.endswith('start'):
     self.assertEqual(strict_json((d/'ledger.json').read_bytes())['actions'][q['id']]['state'],'PENDING');f.q=copy.deepcopy(b);raise OSError('uncertain POST')
   f.before=before
   try:
    with patch.object(c.ledger,'_save_pending',side_effect=capture):c.start(q)
    self.assertEqual(c.report(q['id'])['state'],'UNKNOWN');self.assertTrue(c.ledger.data['unknown_lock']);self.assertTrue(proofs[0].used)
    f.before=lambda *a:None;c.stop(q['id']);c.status(q['id']);self.assertEqual(c.report(q['id'])['state'],'UNKNOWN');self.assertEqual(f.stops()[0][2]['id'],q['id']);self.assertEqual(len(f.starts()),1)
    with self.assertRaises(Refused):c._exchange(c.ledger.data['actions'][q['id']],'start','POST',ROOT+'start',q,_capacity_proof=proofs[0])
    c.start(q);self.assertEqual(len(f.starts()),1)
   finally:c.close()
   c=Controller(d,f,p)
   try:
    self.assertIsNone(c._start_capacity_proof);self.assertTrue(c.ledger.data['unknown_lock']);c.start(q);self.assertEqual(len(f.starts()),1)
    with self.assertRaises(Refused):proofs[0].consume(c.ledger,c.ledger.data['actions'][q['id']])
   finally:c.close()

if __name__=='__main__':unittest.main()
