"""Bounded refused cell/type evidence; never an admission or cleanup proof."""
import re

CODE = 'block_menu_unknown_geometry_provider'

def valid(value):
    if type(value) is not dict or set(value) != {'schema_version','x','y','z','provider_class'}:
        return False
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        return False
    if any(type(value[k]) is not int or not -2147483648 <= value[k] <= 2147483647 for k in ('x','y','z')):
        return False
    name = value['provider_class']
    return type(name) is str and (name == 'unclassified_provider' or
        len(name) <= 160 and name.startswith('net.minecraft.world.level.block.')
        and re.fullmatch(r'[A-Za-z0-9_.$]+', name) is not None)
