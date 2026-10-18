"""Discoverable standalone guard; ordinary-job concurrent policy is not enabled."""
from copy import deepcopy
import hashlib
from pathlib import Path
from mdc_skills.fall_rescue import guard
from mdc_toolbox.contracts import obj, integer, validate_schema, ToolboxError
from .inventory import RESULT_SCHEMA

SCHEMA = obj({'duration_ms': {**integer(1000, 600000), 'default': 60000}}, ())


def definitions():
    root = Path(__file__).resolve().parents[2]
    paths = [Path(__file__), root / 'mdc_skills/fall_rescue.py']
    return [{'capability': 'fall_rescue_guard', 'capability_version': 1, 'group': 'mobility',
        'level': 'bounded_composite', 'description': 'Hold one explicit owner lease for bounded local water-bucket fall rescue.',
        'input_schema': deepcopy(SCHEMA), 'result_schema': deepcopy(RESULT_SCHEMA), 'observation_profile': 'player',
        'native_features': ['native-fall-rescue-owner-guard/1'],
        'bounds': {'default_duration_ms': 60000, 'duration_ms': [1000, 600000], 'native_lease_ms': 5000,
            'owner_renew_interval_ms': 1000, 'max_episodes': 1,
            'minimum_action_budget': 'ceil(duration_ms/1000)+3',
            'minimum_observation_budget': 'ceil(duration_ms/250)+3',
            'minimum_deadline_seconds': 'duration_ms/1000+2'},
        'prerequisites': ['request_only_policy', 'private_singleplayer', 'known_previous_owner_outcome',
            'water_bucket_in_hotbar', 'native_fences_ready', 'external_controller_absent_or_verified_idle'],
        'cancel_granularity': 'same_owner_control_boundary_then_native_disarm', 'resume_supported': False,
        'planner_available': False, 'implementation_status': 'implemented', 'adapter_status': 'implemented',
        'known_limits': ['Standalone guard occupies the sole public job owner; concurrent movement/combat jobs are refused.',
            'Overworld/End supported inert full-solid top with air placement only; no Nether, void, pearls, or guaranteed survival.',
            'One native use attempt per episode. Unknown writes are never replayed; original job remains quarantined.',
            'Status is delivered through original job events. Cancel disarms on the same owner thread.',
            'A stalled owner stops renewing; native authorization expires within five seconds.',
            'Server evidence is correlated water/bucket/landed-alive state, not a packet acknowledgement or counterfactual survival proof.'],
        'source_fingerprints': [{'path': 'capability-runtime/' + str(p.relative_to(root)),
            'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
        'validation': {'offline': 'focused_tests_available', 'live': 'not_run'}}]


def invoke(capability, runtime, arguments, control):
    if capability != 'fall_rescue_guard':
        raise ToolboxError('capability_unavailable', 'Unknown fall-rescue capability')
    validate_schema(arguments, SCHEMA)
    return guard(runtime, control, **deepcopy(arguments))
