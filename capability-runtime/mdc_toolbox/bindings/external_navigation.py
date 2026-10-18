"""Public explicit stop of the supported external controller; no path start."""
from copy import deepcopy
import hashlib
from pathlib import Path
from mdc_skills.external_navigation import stop,VERSION
from mdc_toolbox.contracts import obj,integer,validate_schema,ToolboxError
from .inventory import RESULT_SCHEMA
SCHEMA=obj({'timeout_ms':{**integer(1000,10000),'default':5000}},())
def definitions():
    root=Path(__file__).resolve().parents[2];paths=[Path(__file__),root/'mdc_skills/external_navigation.py']
    return [{'capability':'stop_external_navigation','capability_version':1,'group':'mobility','level':'bounded_composite',
        'description':'Request one safe Baritone cancellation and verify actual idle on two distinct native ticks.',
        'input_schema':deepcopy(SCHEMA),'result_schema':deepcopy(RESULT_SCHEMA),'observation_profile':'player',
        'native_features':[VERSION],'bounds':{'timeout_ms':[1000,10000],'stop_requests':1,'idle_samples':2},
        'prerequisites':['request_only_policy','private_singleplayer','supported_pinned_Baritone_API','no_unknown_MDC_owner','native_fall_guard_disarmed'],
        'cancel_granularity':'no_second_stop_then_bounded_original_idle_verification','resume_supported':False,'planner_available':False,
        'implementation_status':'implemented','adapter_status':'implemented',
        'known_limits':['Explicit cancellation can stop an unmanaged Baritone task; it never resumes it.',
            'A true API cancel return is not completion. Unknown outcome retains the exact owner and blocks new work.',
            'Physical safety is separate from released controls. No forceCancel, key clearing or route start.',
            'Requires max_observations >= ceil(timeout_ms/100)+3 and deadline_seconds >= timeout_ms/1000+3.'],
        'source_fingerprints':[{'path':'capability-runtime/'+str(p.relative_to(root)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
        'validation':{'offline':'synthetic_owner_chain_and_native_lifecycle_passed','live':'not_run'}}]
def invoke(capability,runtime,arguments,control):
    if capability!='stop_external_navigation':raise ToolboxError('capability_unavailable','Unknown external navigation capability')
    validate_schema(arguments,SCHEMA);return stop(runtime,control,**deepcopy(arguments))
