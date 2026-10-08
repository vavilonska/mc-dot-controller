"""Observe native state through an explicit queue and write private local output.

Output includes player identity, inventory, and position. Keep it private.
Importing this module does not create a client, observe, or write files.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import sys
import time

def item_view(item, selected=None):
    if not isinstance(item, dict) or 'empty' not in item:
        return None
    value = {key: item.get(key) for key in ('slot', 'count', 'empty', 'damage', 'max_damage')}
    value['item_id'] = item.get('id')
    if selected is not None:
        value['selected'] = item.get('slot') == selected
    return value


def once(client, output_directory):
    """Write one private state snapshot to the caller-selected directory."""
    root = Path(output_directory)
    request = client.submit({'op': 'observe'})
    result = client.wait(request, 15)
    if result.get('status') != 'succeeded':
        return False
    observed = result['result']
    player = observed.get('state', {}).get('player', {})
    when = datetime.datetime.fromtimestamp(result['finished_at'], datetime.timezone.utc).isoformat()
    selected = player.get('selected_slot')
    slots = [item_view(item, selected) for item in player.get('inventory', [])]
    slots = [item for item in slots if item is not None]
    armor = [item_view(item) for item in player.get('armor', [])]
    armor = [item for item in armor if item is not None]
    health = player.get('health')
    output = {
        'observed_at': when,
        'source': 'authenticated_native_minecraft_observation',
        'connected': observed['status'].get('in_world'),
        'player_name': player.get('name'),
        'world': player.get('dimension'),
        'game_mode': player.get('gamemode'),
        'dead': health <= 0 if isinstance(health, (float, int)) else None,
        'health': health,
        'max_health': player.get('max_health'),
        'food': player.get('food'),
        'saturation': player.get('saturation'),
        'position': {key: player.get(key) for key in ('x', 'y', 'z')},
        'yaw': player.get('yaw'),
        'pitch': player.get('pitch'),
        'selected_hotbar_slot': selected,
        'inventory_observed_at': when,
        'inventory': [item for item in slots if item['empty'] is False],
        'inventory_slots': slots,
        'inventory_slot_count': player.get('inventory_total'),
        'inventory_complete': player.get('inventory_truncated') is False if 'inventory_truncated' in player else None,
        'inventory_groups': {'main': list(range(9, 36)), 'hotbar': list(range(9))} if player.get('inventory_total') == 36 else None,
        'armor': armor,
        'armor_complete': len(armor) == 4 if 'armor' in player else None,
        'offhand': item_view(player.get('offhand')),
    }
    root.mkdir(exist_ok=True, mode=0o700)
    temporary = root / 'state.tmp'
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(root / 'state.json')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue', required=True, type=Path,
                        help='Existing resident-controller mailbox directory')
    parser.add_argument('--output-dir', required=True, type=Path,
                        help='Private directory for player/inventory/position snapshots')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()

    # Resolve the checked-in sibling from this file, independent of cwd. Defer
    # loading it until after argument parsing so --help needs no queue or client.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'resident-controller'))
    from resident_controller.ipc import QueueClient

    client = QueueClient(args.queue)
    root = args.output_dir
    if args.once:
        return 0 if once(client, root) else 1
    root.mkdir(exist_ok=True, mode=0o700)
    (root / 'state-exporter.pid').write_text(str(os.getpid()))
    while not (root / 'stop-state-exporter').exists():
        try:
            once(client, root)
        except Exception as error:
            print(type(error).__name__, flush=True)
        time.sleep(10)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
