#!/usr/bin/env python3
"""Verify three package identities, then invoke the frozen exact offline builder."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output',required=True);a=p.parse_args()
W=Path(__file__).resolve().parent;R=Path(a.root).resolve();sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
for pin in json.loads((W/'PACKAGE-PINS.json').read_text()).values():
 for n,k in [('INDEX.json','index_sha256'),('SHA256SUMS','sha256sums_sha256')]:assert sha(R/pin['directory']/n)==pin[k],n
subprocess.run([sys.executable,str(W/'build-and-test.py'),'--root',str(R),'--output',str(Path(a.output).resolve())],check=True)
