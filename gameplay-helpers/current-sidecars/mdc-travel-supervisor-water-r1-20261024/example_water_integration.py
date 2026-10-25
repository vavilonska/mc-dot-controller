"""No HTTP on import. Keep the pinned r1.1 directory on sys.path BEFORE import."""
from water_supervisor import WaterFirstSupervisor
from travel_supervisor import HttpTransport
from boundary_contract import bound_pre_input_rejection


def run_existing_water_mission(c, boundary_classifier, mission_builder, weapon_slot,
                               lock_path, transport=None):
    sv = WaterFirstSupervisor(c, transport or HttpTransport(c.token),
        boundary_classifier or bound_pre_input_rejection,
        weapon_slot=weapon_slot, lock_path=lock_path)
    return sv.run(lambda: mission_builder(c, sv), c.out/'HANDOFF')
