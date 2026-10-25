from pathlib import Path
import sys
FROZEN_V3_ROOT=Path(__file__).resolve().parents[2]/'interaction3-controller'
if not (FROZEN_V3_ROOT/'interaction3_controller/controller.py').is_file():raise RuntimeError('paired frozen v3 reader required')
if str(FROZEN_V3_ROOT) not in sys.path:sys.path.insert(0,str(FROZEN_V3_ROOT))
from interaction3_controller.controller import Controller as V3Controller
from interaction3_controller import schema as v3_schema
from interaction3_controller.legacy import PROFILE as V3_PROFILE,legacy,Ledger,Refused,encode,strict_json,RawReply,MAX_RESPONSE
PROFILE='recovery_navigation_v4'
ROOT='/control/recovery-interaction/v3/'
