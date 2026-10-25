"""Keep both historical readers byte-identical; select by stored original profile."""
from pathlib import Path
import sys

FROZEN_V1_ROOT=Path(__file__).resolve().parents[2]/'interaction-controller'
if not (FROZEN_V1_ROOT/'interaction_controller'/'controller.py').is_file():
    raise RuntimeError('paired frozen interaction v1 reader required')
if str(FROZEN_V1_ROOT) not in sys.path:sys.path.insert(0,str(FROZEN_V1_ROOT))
from interaction_controller.controller import Controller as V1Controller
from interaction_controller import schema as v1_schema
from interaction_controller.journal import NEW_PROFILE as V1_PROFILE
from interaction_controller.legacy import legacy,Ledger,Refused,encode,strict_json,RawReply,MAX_RESPONSE

PROFILE='recovery_interaction_v2'
ROOT='/control/recovery-interaction/v2/'
