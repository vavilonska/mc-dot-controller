"""Bounded display of a fully archived historical survey; never action input."""
from copy import deepcopy
from .contracts import ToolboxError, json_data

MAX_CELLS = 2048
DEFAULT_CELLS = 1024
MAX_BYTES = 1024 * 1024


def cell_limit(bounds):
    count = bounds.get('max_cells', DEFAULT_CELLS)
    if type(count) is not int or not 1 <= count <= MAX_CELLS:
        raise ToolboxError('invalid_request', 'survey_display_max_cells_out_of_bounds', stage='observation')
    return count


def project(result, bounds):
    count = cell_limit(bounds)
    value = deepcopy(result)
    terrain = value.get('terrain')
    if type(terrain) is not dict or type(terrain.get('cells')) is not list:
        raise ToolboxError('observation_unavailable', 'survey_display_terrain_missing', stage='observation')
    cells = terrain['cells']
    total = len(cells)
    # Retain exact observed block identities/properties, never summarize an
    # omitted collision/fluid field as safe. Full cells remain in Runtime receipt.
    terrain['cells'] = [{k: deepcopy(cell[k]) for k in ('x', 'y', 'z', 'id', 'properties') if k in cell}
                        for cell in cells[:count]]
    terrain.update(source_complete=terrain.get('complete') is True,
                   complete=False, display_only=True, execution_authority=False,
                   physics_omitted=True, cells_total=total, cells_returned=len(terrain['cells']),
                   cells_truncated=total > count)
    value.setdefault('coverage', {}).update(terrain_complete=False, source_terrain_complete=terrain['source_complete'],
        terrain_physics_omitted=True, display_cells_returned=len(terrain['cells']), display_cells_total=total,
        display_cells_truncated=total > count)
    value.setdefault('provenance', {}).update(full_payload_retained_in_original_runtime_receipt=True)
    if len(json_data(value)) > MAX_BYTES:
        raise ToolboxError('observation_unavailable', 'survey_display_byte_budget_exceeded', stage='observation')
    return value
