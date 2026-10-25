"""Import-safe integration example. Operator supplies the existing authenticated client.
No game operations occur merely by importing this file.
"""
from travel_supervisor import Supervisor, HttpTransport
from boundary_contract import bound_pre_input_rejection

def run_existing_mission(c, boundary_classifier, mission_builder, weapon_slot, lock_path):
    # Remove g1040's instance c.request=unbounded_GET_wrapper. This transport has
    # finite socket deadlines, no retries, and reuses c.token without file reads.
    supervisor=Supervisor(c,HttpTransport(c.token),boundary_classifier or bound_pre_input_rejection,
                          weapon_slot=weapon_slot,lock_path=lock_path)
    def mission():
        # Existing helpers using c.request are tracked automatically. Prefer
        # supervisor.action_once(fresh_bound_body) for every native work/eat/move.
        # Keep the whole mission inside this function: no assertions or work
        # after the run() call; any known stop intentionally enters idle defense.
        mission_builder(c,supervisor)
    return supervisor.run(mission,c.out/'HANDOFF')
