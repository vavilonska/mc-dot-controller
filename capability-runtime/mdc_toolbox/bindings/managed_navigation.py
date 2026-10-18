"""Supported actual Baritone walking waypoint; orchestration remains with the caller."""
from copy import deepcopy
import hashlib
from pathlib import Path
from mdc_skills.managed_navigation import navigate,VERSION
from mdc_toolbox.contracts import obj,integer,validate_schema,ToolboxError
from .inventory import RESULT_SCHEMA
SCHEMA=obj({'goal':obj({'x':integer(-29999984,29999984),'y':integer(-2048,2048),'z':integer(-29999984,29999984)},('x','y','z')),
    'max_distance':{**integer(1,200),'default':200},'timeout_ms':{**integer(1000,120000),'default':60000},
    'min_health':{**integer(6,20),'default':12}},('goal',))
def definitions():
    root=Path(__file__).resolve().parents[2];paths=[Path(__file__),root/'mdc_skills/managed_navigation.py']
    return [{'capability':'navigate_managed_walk','capability_version':1,'group':'mobility','level':'local_controller',
        'description':'Walk to one bounded waypoint using the supported actual Baritone API under the sole owner.',
        'input_schema':deepcopy(SCHEMA),'result_schema':deepcopy(RESULT_SCHEMA),'observation_profile':'player',
        'native_features':[VERSION],'bounds':{'max_distance':[1,200],'timeout_ms':[1000,120000],'start_requests':1,'safe_cancel_requests':1,'idle_samples':2},
        'prerequisites':['request_only_policy','private_singleplayer_survival','supported_pinned_Baritone_API','actual_input_fence_ready',
            'external_controller_idle','native_fall_guard_disarmed','no_unknown_owner'],
        'cancel_granularity':'one_exact_route_safe_cancel_then_actual_idle','resume_supported':False,'planner_available':False,
        'implementation_status':'implemented','adapter_status':'implemented',
        'known_limits':['Walking only. No boats, swimming, flight, or portal traversal.',
            'Attached fall rescue is unsupported and rejected: this route has a distinct native owner.',
            'Normal chunk loading is permitted; future/unloaded terrain is not certified.',
            'Attack/use is blocked, including door interaction. A blocked request terminates after verified release.',
            'Settings restore only while exactly owned and unchanged; user changes retain UNKNOWN without overwrite.',
            'Original goal/owner replacement or lost mutation receipt never authorizes replay or automatic resume.',
            'Requires max_observations >= ceil(timeout_ms/250)+45 and deadline_seconds >= timeout_ms/1000+15.'],
        'source_fingerprints':[{'path':'capability-runtime/'+str(p.relative_to(root)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
        'validation':{'offline':'focused_owner_and_actual_native_wire_gates_passed','live':'not_run'}}]
def invoke(capability,runtime,arguments,control):
    if capability!='navigate_managed_walk':raise ToolboxError('capability_unavailable','Unknown managed navigation capability')
    validate_schema(arguments,SCHEMA);return navigate(runtime,control,**deepcopy(arguments))
