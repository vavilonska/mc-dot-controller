"""Validate additive recovery state binding inside an already-validated scoped witness."""
from .capability_snapshot import _require, exact

def validate_inventory_recovery(witness, intent):
    spec=intent.get('inventory_recovery');facts=witness.get('facts',{});menu=facts.get('menu',{})
    _require(witness.get('profile')=='state-menu-v1' and intent.get('action')=='click_slot'
        and intent.get('click_type')=='pickup' and intent.get('button')==0
        and type(spec) is dict and set(spec)=={'schema_version','phase','context','selected_slot','inventory','slots'}
        and type(spec.get('schema_version')) is int and spec['schema_version']==1,
        'inventory_recovery_schema')
    _require(spec.get('phase') in ('pickup_hand','store_cursor')
        and exact(spec.get('selected_slot'),facts.get('selected_slot'))
        and exact(spec.get('context'),menu.get('recovery_context'))
        and type(spec.get('context')) is dict
        and set(spec['context'])=={'schema_version','menu_instance','screen_instance','screen_open'}
        and exact(menu.get('container_id'),intent.get('container_id'))
        and exact(menu.get('state_id'),intent.get('expected_menu_state_id'))
        and menu.get('carried',{}).get('item_fingerprint')==intent.get('expected_carried',{}).get('item_fingerprint'),
        'inventory_recovery_binding')
    expected_inventory=[{'slot':row['slot'],'item_fingerprint':row['item']['item_fingerprint']}
                        for row in facts.get('inventory',[])]
    expected_slots=[{key:row[key] for key in ('menu_index','slot_index','container_slot','player_inventory','active')}
                    | ({'inventory_index':row['inventory_index']} if row['player_inventory'] else {})
                    | {'item_fingerprint':row['item']['item_fingerprint']} for row in menu.get('slots',[])]
    _require(exact(spec.get('inventory'),expected_inventory) and exact(spec.get('slots'),expected_slots),
             'inventory_recovery_complete_state')
    index=intent.get('slot')
    _require(type(index) is int and 0<=index<len(expected_slots),'inventory_recovery_slot')
    row=menu['slots'][index];inventory_index=row.get('inventory_index')
    _require(row['player_inventory'] is True and row['active'] is True
        and row['item']['item_fingerprint']==intent.get('expected_slot_item',{}).get('item_fingerprint'),
        'inventory_recovery_endpoint')
    if spec['phase']=='pickup_hand':
        _require(menu['menu_class']=='net.minecraft.world.inventory.InventoryMenu'
            and facts.get('screen_class')=='' and inventory_index in (facts['selected_slot'],40)
            and menu['carried']['empty'] is True and row['item']['empty'] is False
            and menu['slot_permissions'][index]['may_pickup'] is True,'inventory_recovery_hand_pickup')
    else:
        _require(type(inventory_index) is int and 0<=inventory_index<=35
            and menu['carried']['empty'] is False
            and menu['slot_permissions'][index]['may_place_carried'] is True,'inventory_recovery_cursor_storage')
    return spec
