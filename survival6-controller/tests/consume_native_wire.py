"""Read actual production-codec synthetic fixtures, never native/game HTTP.
Arguments point to a preserved wire revision; overbudget bytes are a negative
serializer fixture and are never represented as an accepted HTTP response.
"""
import argparse,hashlib,json,tempfile
from pathlib import Path
from fixtures import *
from survival6_controller import schema
from survival6_controller.legacy import Refused

def consume(wire,observations):
 rows=[];requests=receipts=accepted=oversize=0
 def row(path,kind):
  raw=path.read_bytes();rows.append(dict(path=str(path),kind=kind,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()));return raw
 for f in sorted(wire.glob('*-request.json')):
  q=strict_json(row(f,'request'));schema.request_valid(q);requests+=1
  for rpath in sorted(wire.glob(f.name[:-13]+'-*.json')):
   if rpath==f:continue
   r=strict_json(row(rpath,'receipt'));schema.receipt_valid(r,q);receipts+=1
 class ReadOnlyFixture:
  endpoint=ENDPOINT
  raw=b''
  def request(self,method,path,body=None):
   assert method=='GET'and path==ROOT+'observe'and body is None
   return RawReply(200,self.raw)
 with tempfile.TemporaryDirectory()as t:
  d=Path(t)/'ledger';clone(d);transport=ReadOnlyFixture();c=Controller(d,transport,None)
  try:
   paths=[wire/'observe-no-world.json']+sorted(p for p in observations.glob('*.json')if p.name!='manifest.json')
   for p in paths:
    transport.raw=row(p,'observation'if p.stat().st_size<=65536 else 'overbudget_negative')
    if len(transport.raw)>65536:
     try:c.observe()
     except Refused:oversize+=1
     else:raise AssertionError('overbudget raw accepted')
    else:c.observe();accepted+=1
   assert (d/'ledger.json').read_bytes()==BASE_RAW
  finally:c.close()
 assert requests>=5 and receipts>=10 and accepted>=6 and oversize>=1
 return dict(scope='Actual production serializer on synthetic inputs; no live capture/actions, no HTTP; private actual338 clone unchanged',requests=requests,receipts=receipts,accepted_observations=accepted,overbudget_rejected=oversize,old338_sha256=hashlib.sha256(BASE_RAW).hexdigest(),old338_unchanged=True,files=rows)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--wire',required=True,type=Path);ap.add_argument('--observations',required=True,type=Path);args=ap.parse_args();print(json.dumps(consume(args.wire,args.observations),indent=2))
