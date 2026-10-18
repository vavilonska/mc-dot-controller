import errno,fcntl,hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from resident_controller import diagnostic_archive as a
class ArchiveTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name);self.root=self.base/'queue';self.root.mkdir();(self.root/'.controller.lock').touch()
  for n in ('diagnostics','inbox','working','results'):(self.root/n).mkdir()
  (self.root/'session.json').write_text(json.dumps({'state':'stopped','session_id':'original'}));self.raw=json.dumps({'schema_version':1,'session_id':'original','diagnostics':{'data':'x'*20000}}).encode();self.file=self.root/'diagnostics'/(hashlib.sha256(self.raw).hexdigest()+'.json');self.file.write_bytes(self.raw)
  self.unknown=self.root/'results'/'unknown-original.json';self.unknown.write_text('{"status":"unknown","request_id":"original"}');self.output=self.base/'closed.zip'
 def test_default_keeps_sources_and_unknown_receipts(self):
  r=a.archive(self.root,self.output);self.assertTrue(self.file.exists());self.assertTrue(self.unknown.exists());self.assertFalse(r['replace_verified_closed_diagnostics']);self.assertLess(self.output.stat().st_size,len(self.raw))
 def test_explicit_verified_replacement_and_exact_restore(self):
  r=a.archive(self.root,self.output,replace_verified_closed_diagnostics=True);self.assertFalse(self.file.exists());self.assertTrue(self.unknown.exists());a.restore(self.root,self.output,r['archive_sha256']);self.assertEqual(self.file.read_bytes(),self.raw)
 def test_live_lock_or_session_refused(self):
  with open(self.root/'.controller.lock','r+')as f:
   fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
   with self.assertRaises(BlockingIOError):a.archive(self.root,self.output)
  (self.root/'session.json').write_text('{"state":"ready"}')
  with self.assertRaises(ValueError):a.archive(self.root,self.output)
  self.assertFalse(self.output.exists())
 def test_pending_unknown_request_is_not_touched(self):
  p=self.root/'working'/'pending.json';p.write_text('{}')
  with self.assertRaises(ValueError):a.archive(self.root,self.output)
  self.assertTrue(p.exists());self.assertTrue(self.file.exists())
 def test_unknown_receipt_cannot_be_selected_as_diagnostic(self):
  raw=b'{"status":"unknown","request_id":"original"}';p=self.root/'diagnostics'/(hashlib.sha256(raw).hexdigest()+'.json');p.write_bytes(raw)
  with self.assertRaises(ValueError):a.archive(self.root,self.output)
  self.assertTrue(p.exists())
 def test_symlink_and_digest_mismatch_fail_closed(self):
  self.file.write_bytes(b'changed')
  with self.assertRaises(ValueError):a.archive(self.root,self.output)
  self.file.unlink();self.file.symlink_to(self.unknown)
  with self.assertRaises(OSError):a.archive(self.root,self.output)
 def test_enospc_preserves_all_originals(self):
  with patch('resident_controller.diagnostic_archive.zipfile.ZipFile.writestr',side_effect=OSError(errno.ENOSPC,'full')):
   with self.assertRaises(OSError):a.archive(self.root,self.output,replace_verified_closed_diagnostics=True)
  self.assertEqual(self.file.read_bytes(),self.raw);self.assertTrue(self.unknown.exists())
 def test_changed_source_after_archive_proof_never_unlinked(self):
  verify=a.verify_archive
  def changed(*args,**kw):
   result=verify(*args,**kw);self.file.write_bytes(b'changed');return result
  with patch.object(a,'verify_archive',side_effect=changed),self.assertRaises(ValueError):a.archive(self.root,self.output,replace_verified_closed_diagnostics=True)
  self.assertEqual(self.file.read_bytes(),b'changed');self.assertTrue(self.output.exists())
 def test_wrong_archive_hash_and_existing_restore_mismatch_refused(self):
  r=a.archive(self.root,self.output,replace_verified_closed_diagnostics=True)
  with self.assertRaises(ValueError):a.restore(self.root,self.output,'0'*64)
  self.file.write_bytes(b'other')
  with self.assertRaises(ValueError):a.restore(self.root,self.output,r['archive_sha256'])
  self.assertEqual(self.file.read_bytes(),b'other')
 def test_consumed_archive_never_overwritten(self):
  a.archive(self.root,self.output)
  with self.assertRaises(ValueError):a.archive(self.root,self.output)
 def test_corrupt_archive_after_first_proof_keeps_every_original(self):
  verify=a.verify_archive
  def corrupt(*args,**kw):
   result=verify(*args,**kw);self.output.write_bytes(b'corrupt after verified read');return result
  with patch.object(a,'verify_archive',side_effect=corrupt),self.assertRaises(ValueError):
   a.archive(self.root,self.output,replace_verified_closed_diagnostics=True)
  self.assertEqual(self.file.read_bytes(),self.raw);self.assertTrue(self.unknown.exists())
 def test_swapped_archive_after_first_proof_keeps_every_original(self):
  verify=a.verify_archive;held=self.base/'original.zip'
  def swap(*args,**kw):
   result=verify(*args,**kw);raw=self.output.read_bytes();self.output.rename(held);self.output.write_bytes(raw);return result
  with patch.object(a,'verify_archive',side_effect=swap),self.assertRaises(ValueError):
   a.archive(self.root,self.output,replace_verified_closed_diagnostics=True)
  self.assertEqual(self.file.read_bytes(),self.raw);self.assertTrue(held.exists())
 def test_hash_and_zip_parse_share_descriptor_and_reject_midproof_swap(self):
  zip_class=a.zipfile.ZipFile;parsed=[];held=self.base/'old-inode.zip'
  def opened(file,*args,**kw):
   mode=args[0] if args else kw.get('mode','r')
   if mode=='r':
    self.assertTrue(hasattr(file,'fileno'));parsed.append(file.fileno())
    raw=self.output.read_bytes();self.output.rename(held);self.output.write_bytes(raw)
   return zip_class(file,*args,**kw)
  with patch.object(a.zipfile,'ZipFile',side_effect=opened),self.assertRaises(ValueError):
   a.archive(self.root,self.output,replace_verified_closed_diagnostics=True)
  self.assertEqual(len(parsed),1);self.assertEqual(self.file.read_bytes(),self.raw)
 def test_archive_and_restore_symlink_parent_rejected(self):
  real=self.base/'real';real.mkdir();alias=self.base/'alias';alias.symlink_to(real,target_is_directory=True)
  with self.assertRaises(ValueError):a.archive(self.root,alias/'archive.zip',replace_verified_closed_diagnostics=True)
  self.assertEqual(self.file.read_bytes(),self.raw);self.assertFalse((real/'archive.zip').exists())
  r=a.archive(self.root,real/'archive.zip')
  with self.assertRaises(ValueError):a.restore(self.root,alias/'archive.zip',r['archive_sha256'])
 def test_archive_parent_swap_after_proof_preserves_sources(self):
  directory=self.base/'archives';directory.mkdir();self.output=directory/'closed.zip';verify=a.verify_archive
  def swap(*args,**kw):
   result=verify(*args,**kw);directory.rename(self.base/'archives-old');directory.mkdir();return result
  with patch.object(a,'verify_archive',side_effect=swap),self.assertRaises((ValueError,FileNotFoundError)):
   a.archive(self.root,self.output,replace_verified_closed_diagnostics=True)
  self.assertEqual(self.file.read_bytes(),self.raw)
 def test_source_change_after_final_archive_proof_preserved(self):
  verify=a._verify_archive_stream;calls=[]
  def change(*args,**kw):
   result=verify(*args,**kw);calls.append(1)
   if len(calls)==2:self.file.write_bytes(b'changed after final archive proof')
   return result
  with patch.object(a,'_verify_archive_stream',side_effect=change),self.assertRaises(ValueError):
   a.archive(self.root,self.output,replace_verified_closed_diagnostics=True)
  self.assertEqual(self.file.read_bytes(),b'changed after final archive proof');self.assertTrue(self.unknown.exists())
 def test_restore_keeps_verified_descriptor_and_rejects_path_swap(self):
  r=a.archive(self.root,self.output,replace_verified_closed_diagnostics=True);verify=a.verify_archive;held=self.base/'saved.zip'
  def swap(*args,**kw):
   result=verify(*args,**kw);raw=self.output.read_bytes();self.output.rename(held);self.output.write_bytes(raw);return result
  with patch.object(a,'verify_archive',side_effect=swap),self.assertRaises(ValueError):a.restore(self.root,self.output,r['archive_sha256'])
  self.assertFalse(self.file.exists());self.assertTrue(held.exists());self.assertTrue(self.unknown.exists())
 def test_archive_write_lock_is_held_through_final_proof(self):
  verify=a.verify_archive
  def competing(*args,**kw):
   result=verify(*args,**kw)
   with open(self.output,'rb')as other:
    with self.assertRaises(BlockingIOError):fcntl.flock(other.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
   return result
  with patch.object(a,'verify_archive',side_effect=competing):a.archive(self.root,self.output,replace_verified_closed_diagnostics=True)
  self.assertFalse(self.file.exists())
if __name__=='__main__':unittest.main()
