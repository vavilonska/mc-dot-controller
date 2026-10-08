"""Read-only loaded-world scan requests and a bounded observation cache.

These are observations, not a live world mirror. Nothing here plans movement,
holds keys, loads chunks, retries a write, or resumes scans after a restart.
"""
from __future__ import annotations

from collections import OrderedDict
import copy
import re
import time

from .ipc import atomic_json
from .transport import json_bytes

SCAN_OPS = {'scan_start', 'scan_status', 'scan_cancel'}
SCAN_ID = re.compile(r'[A-Za-z0-9_-]{1,64}')
RESOURCE_ID = re.compile(r'[a-z0-9_.-]{1,40}:[a-z0-9/._-]{1,100}')
MAX_CACHED_SCANS = 32
MAX_CACHE_BYTES = 1024 * 1024
MAX_SCAN_BYTES = 256 * 1024
MAX_SCAN_RESULTS = 256


def scan_id(command):
    value = command.get('id', command.get('request_id') if command.get('op') == 'scan_start' else None)
    if not isinstance(value, str) or not SCAN_ID.fullmatch(value):
        raise ValueError('scan_id_1_to_64_letters_digits_hyphen_underscore')
    return value


def start_body(command):
    """Validate before any bridge request, then forward only scan options."""
    body = {'id': scan_id(command), 'mode': command.get('mode', 'both'),
            'max_results': command.get('max_results', 64), 'sort': command.get('sort', 'count')}
    if body['mode'] not in ('ores', 'cherry_sites', 'both', 'blocks', 'biomes', 'surface_sites'):
        raise ValueError('invalid_scan_mode')
    if body['sort'] not in ('count', 'density', 'distance'):
        raise ValueError('scan_sort_count_density_or_distance')
    if type(body['max_results']) is not int or not 1 <= body['max_results'] <= MAX_SCAN_RESULTS:
        raise ValueError('scan_max_results_1_to_256')
    if 'bounds' in command:
        bounds = command['bounds']
        required = {'min_x', 'max_x', 'min_z', 'max_z'}
        allowed = required | {'min_y', 'max_y'}
        if (not isinstance(bounds, dict) or not required <= bounds.keys()
                or not bounds.keys() <= allowed
                or any(type(v) is not int or not -2**31 <= v < 2**31 for v in bounds.values())):
            raise ValueError('invalid_scan_bounds')
        for axis in ('x', 'y', 'z'):
            low, high = 'min_' + axis, 'max_' + axis
            if low in bounds and high in bounds and bounds[low] > bounds[high]:
                raise ValueError('invalid_scan_bounds')
            limit = 1_000_000 if axis == 'y' else 30_000_000
            if any(key in bounds and not -limit <= bounds[key] <= limit for key in (low, high)):
                raise ValueError('invalid_scan_bounds')
        width = bounds['max_x'] - bounds['min_x'] + 1
        depth = bounds['max_z'] - bounds['min_z'] + 1
        chunks = ((bounds['max_x'] >> 4) - (bounds['min_x'] >> 4) + 1) * (
            (bounds['max_z'] >> 4) - (bounds['min_z'] >> 4) + 1)
        if width > 2048 or depth > 2048 or chunks > 8192:
            raise ValueError('scan_bounds_too_large')
        body['bounds'] = dict(bounds)
    if 'ore_ids' in command and 'block_ids' in command:
        raise ValueError('scan_use_block_ids_or_ore_ids_not_both')
    for field in ('ore_ids', 'block_ids', 'biome_ids'):
        if field not in command:
            continue
        ids = command[field]
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 32
                or any(not isinstance(value, str)
                       or not RESOURCE_ID.fullmatch(value) for value in ids)):
            raise ValueError('scan_' + field + '_requires_1_to_32_registry_ids')
        body[field] = list(ids)
    if body['mode'] == 'biomes':
        if 'biome_ids' not in body:
            raise ValueError('scan_biome_ids_required')
        if 'block_ids' in body or 'ore_ids' in body:
            raise ValueError('scan_biomes_block_filter_use_blocks_with_biome_ids')
    if 'require_water' in command:
        if type(command['require_water']) is not bool:
            raise ValueError('scan_require_water_must_be_boolean')
        body['require_water'] = command['require_water']
    if 'water_radius' in command:
        if type(command['water_radius']) is not int or not 0 <= command['water_radius'] <= 128:
            raise ValueError('scan_water_radius_0_to_128')
        body['water_radius'] = command['water_radius']
    return body


def validate_scan(response, expected_id):
    """Reject mismatched/unsupported acknowledgements without inventing results."""
    if (not isinstance(response, dict) or type(response.get('scan_schema_version')) is not int
            or response['scan_schema_version'] != 1 or response.get('scan_id') != expected_id
            or response.get('status') not in ('running', 'succeeded', 'cancelled', 'failed')
            or stamp(response) is None or not isinstance(response.get('coverage'), dict)
            or not isinstance(response.get('results'), dict)
            or any(type(response.get(key)) is not int or response[key] < 0
                   for key in ('started_at_ms', 'observed_at_ms'))
            or len(json_bytes(response)) > MAX_SCAN_BYTES):
        raise ValueError('invalid_scan_response')
    for key in ('ore_clusters', 'cherry_sites', 'block_clusters', 'biome_clusters', 'surface_sites', 'regions'):
        values = response['results'].get(key, [])
        if not isinstance(values, list) or len(values) > MAX_SCAN_RESULTS:
            raise ValueError('invalid_scan_response')
    return response


def stamp(value):
    if not isinstance(value, dict):
        return None
    values = tuple(value.get(key) for key in ('dimension', 'world_generation'))
    return values if all(isinstance(v, str) and 0 < len(v) <= 256 for v in values) else None


class ProspectingCache:
    """Latest snapshot per ID, LRU-bounded, for one observed world/session only."""
    def __init__(self, path, session_id):
        self.path, self.session_id = path, session_id
        self.world = None
        self.entries = OrderedDict()
        self.updated_at = None

    def reset(self):
        self.world = None
        self.entries.clear()
        self.save()

    def observe_world(self, world, *, in_world=True):
        current = stamp(world) if in_world else None
        if current != self.world:
            self.world = current
            self.entries.clear()
            self.save()

    def record(self, response):
        # A retained Java terminal status may describe a previous world. It can
        # be returned with its original stamp, but must never enter this cache.
        if self.world is None or stamp(response) != self.world:
            return False
        scan = copy.deepcopy(response)
        scan['resident_received_at'] = time.time()
        self.entries.pop(scan['scan_id'], None)
        self.entries[scan['scan_id']] = scan
        self.save()
        return scan['scan_id'] in self.entries

    def summary(self):
        return {'schema_version': 1, 'session_id': self.session_id,
                'dimension': self.world[0] if self.world else None,
                'world_generation': self.world[1] if self.world else None,
                'scan_count': len(self.entries), 'updated_at': self.updated_at,
                'historical_observations_only': True,
                'max_scans': MAX_CACHED_SCANS, 'max_bytes': MAX_CACHE_BYTES}

    def snapshot(self):
        return {**self.summary(), 'observations': list(self.entries.values())}

    def save(self):
        self.updated_at = time.time()
        while len(self.entries) > MAX_CACHED_SCANS or len(json_bytes(self.snapshot())) > MAX_CACHE_BYTES:
            self.entries.popitem(last=False)
        atomic_json(self.path, self.snapshot())
