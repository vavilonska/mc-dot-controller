"""Retain all three historical readers; dispatch by stored original profile."""
from pathlib import Path
import sys
FROZEN_V2_ROOT=Path(__file__).resolve().parents[2]/'interaction2-controller'
if not (FROZEN_V2_ROOT/'interaction2_controller/controller.py').is_file():raise RuntimeError('paired frozen v2 reader required')
if str(FROZEN_V2_ROOT) not in sys.path:sys.path.insert(0,str(FROZEN_V2_ROOT))
from interaction2_controller.controller import Controller as V2Controller
from interaction2_controller import schema as v2_schema
from interaction2_controller.legacy import PROFILE as V2_PROFILE,legacy,Ledger,Refused,encode,strict_json,RawReply,MAX_RESPONSE
PROFILE='recovery_interaction_v3'
ROOT='/control/recovery-interaction/v3/'
