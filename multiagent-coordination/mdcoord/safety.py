"""Conservative fixture preflight. No route inference across unknown cells."""
import math
from .schema import require
from .threats import ThreatStore


def preflight(plan, grant, snapshot, threats=None, proof_id=None):
    require(snapshot['context'] == grant.context.wire() == plan['context'], 'context_changed')
    kind = plan['intent']['kind']
    required = {'terrain'} if kind == 'follow_path' else {'entities'}
    require(snapshot['sections'].get('player', {}).get('freshness') == 'fresh', 'player_not_fresh')
    require(required <= plan['based_on'].keys(), 'missing_required_revision')
    for section, revision in plan['based_on'].items():
        current = snapshot['sections'].get(section)
        require(current is not None and current['revision'] == revision, 'revision_conflict')
        require(current['freshness'] == 'fresh', 'observation_not_fresh')
    player = snapshot['sections']['player']['data']
    p = plan['preconditions']
    require(player['alive'] is True and player['grounded'] is True and player['screen_closed'] is True
            and player['health'] >= p['min_health'], 'precondition_failed')
    require(grant.contains(player), 'outside_authorized_bounds')
    if kind == 'defend_entity':
        target = plan['intent']
        require(target['target_uuid'] in grant.allowed_targets, 'target_not_authorized')
        matches = [entity for entity in snapshot['sections']['entities']['data']['entities']
                   if entity['uuid'] == target['target_uuid'] and entity['entity_id'] == target['target_entity_id']
                   and entity['type'] == target['target_type']]
        require(len(matches) == 1 and matches[0]['alive'] is True and matches[0]['attackable'] is True,
                'target_not_observed')
        return
    terrain = snapshot['sections']['terrain']['data']
    require(terrain['complete'], 'terrain_incomplete')
    cells = {(c['x'], c['y'], c['z']): c for c in terrain['cells']}
    def safe_cell(point):
        # MVP supports centered, cardinal, level walking only. No jumps, fluids or drops.
        require(point['x'] % 1 == .5 and point['z'] % 1 == .5 and point['y'] % 1 == 0,
                'flat_centered_route_required')
        block = (math.floor(point['x']), int(point['y']), math.floor(point['z']))
        for dy in (-1, 0, 1):
            cell = cells.get((block[0], block[1] + dy, block[2]))
            require(cell is not None and cell['loaded'] is True and cell['hazard'] is False
                    and cell['fluid'] is False, 'unknown_or_hazardous_corridor')
            require(cell['full_support'] is True if dy == -1 else cell['passable'] is True,
                    'blocked_corridor')
    previous = {key: player[key] for key in ('x', 'y', 'z')}
    require(previous == p['expected_position'], 'expected_start_changed')
    safe_cell(previous)
    for waypoint in plan['intent']['waypoints']:
        require(grant.contains(waypoint), 'outside_authorized_bounds')
        require(waypoint['y'] == previous['y'] and
                abs(waypoint['x'] - previous['x']) + abs(waypoint['z'] - previous['z']) == 1,
                'nonadjacent_or_vertical_route')
        safe_cell(waypoint)
        previous = waypoint
    # Content revision equality, even for entities, is not evidence of safety.
    # Recheck the latest entities independently from the planner's dependencies.
    entities = snapshot['sections'].get('entities')
    require(entities is not None, 'entities_missing')
    require(entities.get('freshness') == 'fresh', 'entities_not_fresh')
    require(entities['data'].get('truncated') is False, 'entities_incomplete')
    require(type(threats) is ThreatStore, 'threat_proof_missing')
    return threats.require_clearance(snapshot, p['expected_position'], plan['intent']['waypoints'],
                                     proof_id=proof_id)
