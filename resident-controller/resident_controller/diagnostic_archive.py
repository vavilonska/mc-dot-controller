"""Explicit lossless archival of stopped, cooperatively locked Resident diagnostics.

No world, source, backup, journal, result/UNKNOWN receipt, or live log is selected.
Locks coordinate participating processes, not arbitrary hostile same-user writers.
"""
from contextlib import contextmanager
import argparse,fcntl,hashlib,json,os,re,stat,zipfile
from pathlib import Path
from .session_diagnostics import MAX_DIAGNOSTIC_BYTES,MAX_DIAGNOSTIC_FILES

NAME=re.compile(r'[0-9a-f]{64}\.json')
MAX_MANIFEST=256*1024

def require(ok,reason):
    if not ok:raise ValueError(reason)

def sha(raw):return hashlib.sha256(raw).hexdigest()
def signature(s):return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def identity(s):return (s.st_dev,s.st_ino)

def safe_parents(path):
    path=Path(path).absolute()
    require('..' not in path.parts,'archive_parent_traversal_forbidden')
    for p in path.parents:
        require(stat.S_ISDIR(os.lstat(p).st_mode),'archive_nonsymlink_parent_required')
    return path

def require_same_file(path,fd,expected=None):
    path=safe_parents(path);current=os.lstat(path);held=os.fstat(fd)
    require(stat.S_ISREG(current.st_mode) and stat.S_ISREG(held.st_mode)
        and signature(current)==signature(held),'archive_path_descriptor_changed')
    if expected is not None:require(signature(held)==expected,'archive_file_changed_after_proof')
    return signature(held)

def regular_bytes(path,limit):
    path=safe_parents(path);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=require_same_file(path,fd);require(before[2]<=limit,'archive_regular_bounded_file_required')
        with os.fdopen(fd,'rb',closefd=False)as stream:raw=stream.read(limit+1)
        require(len(raw)<=limit,'archive_file_size_changed');require_same_file(path,fd,before)
        return raw,before
    finally:os.close(fd)

@contextmanager
def closed_queue(root):
    root=safe_parents(root);st=os.lstat(root);require(stat.S_ISDIR(st.st_mode),'archive_nonsymlink_queue_required')
    fd=os.open(root/'.controller.lock',os.O_RDWR|os.O_NOFOLLOW)
    try:
        require_same_file(root/'.controller.lock',fd);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        require(identity(os.lstat(root))==identity(st),'archive_queue_changed')
        session=json.loads(regular_bytes(root/'session.json',1024*1024)[0])
        require(session.get('state')=='stopped','archive_closed_resident_required')
        for name in ('inbox','working'):
            directory=root/name
            require(directory.is_dir()and not directory.is_symlink()and not any(directory.iterdir()),'archive_pending_or_unknown_request_retained')
        yield root
        require(identity(os.lstat(root))==identity(st),'archive_queue_changed')
    finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)

def inspect(root):
    directory=root/'diagnostics';require(directory.is_dir()and not directory.is_symlink(),'archive_diagnostics_directory_required')
    paths=sorted(directory.iterdir());require(len(paths)<=MAX_DIAGNOSTIC_FILES,'archive_diagnostic_count_bound')
    rows=[]
    for p in paths:
        require(NAME.fullmatch(p.name)is not None,'archive_only_digest_named_diagnostics_allowed')
        raw,sig=regular_bytes(p,MAX_DIAGNOSTIC_BYTES)
        require(sha(raw)==p.stem,'archive_source_digest_mismatch')
        value=json.loads(raw);require(type(value)is dict and set(value)=={'schema_version','session_id','diagnostics'}
            and type(value['schema_version'])is int and value['schema_version']==1 and type(value['session_id'])is str
            and bool(value['session_id']) and type(value['diagnostics'])is dict,'archive_diagnostic_schema_only')
        rows.append({'path':'diagnostics/'+p.name,'bytes':len(raw),'sha256':sha(raw),'source_signature':sig})
    require(rows,'archive_no_diagnostics');return rows

@contextmanager
def archive_reader(path):
    path=safe_parents(path);fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb',buffering=0)as stream:
        require_same_file(path,fd);fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
        try:yield path,stream
        finally:fcntl.flock(fd,fcntl.LOCK_UN)

def _verify_archive_stream(path,stream,expected_sha=None):
    # Hashing and ZIP parsing use the SAME retained descriptor. A pathname swap
    # cannot make the digest describe one file while the parsed payload is another.
    before=require_same_file(path,stream.fileno())
    require(before[2]<=MAX_DIAGNOSTIC_FILES*(MAX_DIAGNOSTIC_BYTES+1024)+MAX_MANIFEST,'archive_file_bound')
    stream.seek(0);h=hashlib.sha256()
    while chunk:=stream.read(65536):h.update(chunk)
    digest=h.hexdigest();require(expected_sha is None or digest==expected_sha,'archive_sha256_mismatch')
    stream.seek(0)
    with zipfile.ZipFile(stream)as z:
        require(len(z.infolist())<=MAX_DIAGNOSTIC_FILES+1,'archive_member_count_bound')
        info=z.getinfo('restore-manifest.json');require(info.file_size<=MAX_MANIFEST,'archive_manifest_bound')
        m=json.loads(z.read(info));require(type(m)is dict and set(m)=={'schema_version','kind','files'}and type(m['schema_version'])is int and m['schema_version']==1
            and m['kind']=='closed_resident_diagnostics'and type(m['files'])is list and 0<len(m['files'])<=MAX_DIAGNOSTIC_FILES,'archive_manifest_invalid')
        expected={'restore-manifest.json'}
        for row in m['files']:
            require(type(row)is dict and set(row)=={'path','bytes','sha256','source_signature'},'archive_row_invalid')
            name=row['path'];require(type(name)is str and name.startswith('diagnostics/')and NAME.fullmatch(name[12:])is not None and name not in expected,'archive_member_path_invalid')
            require(type(row['bytes'])is int and 0<row['bytes']<=MAX_DIAGNOSTIC_BYTES and row['sha256']==name[12:-5],'archive_member_size_or_digest_invalid')
            require(type(row['source_signature'])is list and len(row['source_signature'])==5 and all(type(v)is int and v>=0 for v in row['source_signature']),'archive_source_signature_invalid')
            expected.add(name);i=z.getinfo(name);require(i.file_size==row['bytes'],'archive_member_size_mismatch');content=z.read(i)
            require(sha(content)==row['sha256'],'archive_member_digest_mismatch')
        require(len(z.infolist())==len(expected)and set(z.namelist())==expected,'archive_extra_or_duplicate_member')
    require_same_file(path,stream.fileno(),before)
    return digest,m

def verify_archive(path,expected_sha=None,*,stream=None):
    if stream is not None:return _verify_archive_stream(path,stream,expected_sha)
    with archive_reader(path)as(path,held):return _verify_archive_stream(path,held,expected_sha)

def write_exclusive(path,raw):
    path=safe_parents(path);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb')as f:f.write(raw);f.flush();os.fsync(f.fileno());require_same_file(path,f.fileno())

def sync_dir(path):
    path=safe_parents(path);fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def archive(root,output,*,replace_verified_closed_diagnostics=False):
    output=safe_parents(output);require(not output.exists()and not output.is_symlink(),'archive_output_already_consumed')
    parent_identity=identity(os.lstat(output.parent))
    with closed_queue(root)as root:
        require(root not in output.parents,'archive_output_must_be_outside_queue')
        rows=inspect(root);manifest={'schema_version':1,'kind':'closed_resident_diagnostics','files':rows}
        diagnostics_identity=identity(os.lstat(root/'diagnostics'))
        fd=os.open(output,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        # One retained descriptor and exclusive cooperative writer lock through
        # capture, proof, durable restore receipt and explicit source replacement.
        with os.fdopen(fd,'w+b',buffering=0)as stream:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6)as z:
                z.writestr('restore-manifest.json',json.dumps(manifest,sort_keys=True))
                for row in rows:
                    raw,_=regular_bytes(root/row['path'],MAX_DIAGNOSTIC_BYTES)
                    require(sha(raw)==row['sha256'],'archive_source_changed_during_capture');z.writestr(row['path'],raw)
            stream.flush();os.fsync(fd)
            digest,checked=verify_archive(output,stream=stream);require(checked==json.loads(json.dumps(manifest)),'archive_manifest_roundtrip_mismatch')
            for row in rows:
                raw,sig=regular_bytes(root/row['path'],MAX_DIAGNOSTIC_BYTES)
                require(list(sig)==list(row['source_signature'])and sha(raw)==row['sha256'],'archive_source_changed_no_replacement')
            receipt={'schema_version':1,'archive':str(output),'archive_sha256':digest,'restore_manifest':manifest,
                'verified_lossless':True,'replace_verified_closed_diagnostics':bool(replace_verified_closed_diagnostics),
                'replacement_requested_after_complete_hash_proof':bool(replace_verified_closed_diagnostics),
                'writer_contract':'closed_resident_and_cooperating_archive_writers_only','absolute_same_user_immutability_claimed':False}
            write_exclusive(Path(str(output)+'.restore.json'),(json.dumps(receipt,indent=2)+'\n').encode());sync_dir(output.parent)
            # A callback or filesystem race after initial proof must not turn a
            # corrupted/replaced archive into permission to unlink original data.
            require(identity(os.lstat(output.parent))==parent_identity,'archive_parent_changed')
            final_digest,final_manifest=_verify_archive_stream(output,stream,digest)
            require(final_digest==digest and final_manifest==checked,'archive_final_proof_changed')
            final_signature=require_same_file(output,fd)
            require(identity(os.lstat(root/'diagnostics'))==diagnostics_identity,'archive_diagnostics_changed')
            if replace_verified_closed_diagnostics:
                for row in rows:
                    require_same_file(output,fd,final_signature)
                    source=safe_parents(root/row['path'])
                    require(signature(os.lstat(source))==tuple(row['source_signature'])and stat.S_ISREG(os.lstat(source).st_mode),'archive_source_changed_no_replacement')
                    source.unlink()
                sync_dir(root/'diagnostics')
            require_same_file(output,fd,final_signature)
            return receipt

def restore(root,archive_path,expected_sha256):
    require(type(expected_sha256)is str and re.fullmatch(r'[0-9a-f]{64}',expected_sha256)is not None,'restore_exact_archive_hash_required')
    with closed_queue(root)as root,archive_reader(archive_path)as(path,stream):
        digest,m=verify_archive(path,expected_sha256,stream=stream);directory=root/'diagnostics'
        require(directory.is_dir()and not directory.is_symlink(),'restore_diagnostics_directory_required')
        before=require_same_file(path,stream.fileno());stream.seek(0)
        with zipfile.ZipFile(stream)as z:
            for row in m['files']:
                p=root/row['path']
                if p.exists()or p.is_symlink():require(sha(regular_bytes(p,MAX_DIAGNOSTIC_BYTES)[0])==row['sha256'],'restore_existing_file_mismatch')
            written=[]
            for row in m['files']:
                require_same_file(path,stream.fileno(),before);p=root/row['path'];raw=z.read(row['path'])
                require(len(raw)==row['bytes']and sha(raw)==row['sha256'],'restore_archive_changed')
                if not p.exists():write_exclusive(p,raw);written.append(row['path'])
        require_same_file(path,stream.fileno(),before)
        sync_dir(directory);return {'archive_sha256':digest,'restored':written,'verified':len(m['files']),'identity_receipts_touched':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=('archive','restore'));p.add_argument('--queue',required=True);p.add_argument('--archive',required=True)
    p.add_argument('--replace-verified-closed-diagnostics',action='store_true');p.add_argument('--expected-archive-sha256');a=p.parse_args()
    if a.operation=='restore':
        require(not a.replace_verified_closed_diagnostics,'replace_flag_is_archive_only');result=restore(a.queue,a.archive,a.expected_archive_sha256)
    else:
        require(a.expected_archive_sha256 is None,'expected_hash_is_restore_only');result=archive(a.queue,a.archive,replace_verified_closed_diagnostics=a.replace_verified_closed_diagnostics)
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
