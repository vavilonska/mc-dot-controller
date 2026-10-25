from pathlib import Path
import sys
FROZEN_V4_ROOT=Path(__file__).resolve().parents[2]/'navigation4-controller'
if not (FROZEN_V4_ROOT/'navigation4_controller/controller.py').is_file():raise RuntimeError('paired frozen v4 reader required')
if str(FROZEN_V4_ROOT) not in sys.path:sys.path.insert(0,str(FROZEN_V4_ROOT))
from navigation4_controller.controller import Controller as V4Controller
from navigation4_controller import schema as v4_schema
from navigation4_controller.legacy import PROFILE as V4_PROFILE,legacy,Ledger,Refused,encode,strict_json,RawReply,MAX_RESPONSE
PROFILE='recovery_maintenance_v5'
ROOT='/control/recovery-interaction/v3/'
