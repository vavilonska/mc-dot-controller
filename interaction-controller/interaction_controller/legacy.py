"""Frozen sibling reader: legacy records keep their original schema and digest.

No legacy source edits, alternate profiles, owner acquisition or migration writes.
"""
from pathlib import Path
import sys

LEGACY_ROOT = Path(__file__).resolve().parents[2] / 'short-input-controller'
if not (LEGACY_ROOT / 'short_input_controller' / 'controller.py').is_file():
    raise RuntimeError('paired frozen short-input reader is required')
if str(LEGACY_ROOT) not in sys.path:
    sys.path.insert(0, str(LEGACY_ROOT))
from short_input_controller import controller as legacy
from short_input_controller.storage import Ledger, Refused, encode, strict_json
from short_input_controller.transport import RawReply, MAX_RESPONSE
