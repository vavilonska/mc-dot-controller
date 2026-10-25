"""Byte-preserved original readers, including both v5 PLAN proof kinds."""
from pathlib import Path
import sys
SOURCE=Path(__file__).resolve().parents[2]
for name in ('maintenance5-controller','navigation5-controller'):
 root=SOURCE/name
 if not root.is_dir():raise RuntimeError('paired frozen mixed-v5 readers required')
 if str(root) not in sys.path:sys.path.insert(0,str(root))
from navigation5_controller.controller import Controller as OriginalController,SNAPSHOT_READERS
from maintenance5_controller.controller import MaintenanceLedger
from maintenance5_controller.legacy import legacy,Refused,encode,strict_json,RawReply,MAX_RESPONSE
from maintenance5_controller import schema as original_schema
PROFILE='recovery_survival_v6'
ROOT='/control/recovery-interaction/v3/'
