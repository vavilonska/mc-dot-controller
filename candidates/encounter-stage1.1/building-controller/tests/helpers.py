"""Synthetic bridge-shaped data, not a physics simulator or live observation."""
from copy import deepcopy

from building_controller.model import Blueprint, Pos
from building_controller.terrain import Terrain

WORLD = "00000000-0000-4000-8000-000000000001"
SCAN = "00000000-0000-4000-8000-000000000002"


def cell(pos, block="minecraft:air", **changes):
    air = block == "minecraft:air"
    value = dict(**pos.json(), status="loaded", known=True, id=block, id_truncated=False,
                 air=air, properties={}, properties_truncated=False, fluid="minecraft:empty",
                 fluid_truncated=False, fluid_source=False, hazards=[], hazards_exhaustive=False,
                 collision_known=True, collision_empty=air, full_top_support=not air)
    if not air:
        value["collision_bounds"] = [0., 0., 0., 1., 1., 1.]
    value.update(changes)
    return value


def pages(overrides=None, radius=4, vertical=4, limit=128, floor_y=63):
    overrides = overrides or {}
    positions = [Pos(x, y, z) for y in range(64 - vertical, 65 + vertical)
                 for z in range(-radius, radius + 1) for x in range(-radius, radius + 1)]
    result = []
    for offset in range(0, len(positions), limit):
        records = [deepcopy(overrides.get(pos, cell(pos, "minecraft:stone" if pos.y <= floor_y
                                                  else "minecraft:air")))
                   for pos in positions[offset:offset + limit]]
        end = offset + len(records)
        page = dict(ok=True, protocol="mineclient-bridge", schema_version=2, terrain_schema_version=1,
                    world_generation=WORLD, dimension="minecraft:overworld", generation=SCAN,
                    consistency="live_pages", game_time=100, response_game_time=100,
                    read_only=True, loaded_chunks_only=True, origin={"x": 0, "y": 64, "z": 0},
                    radius=radius, vertical=vertical, order="x_then_z_then_y", offset=offset,
                    next_offset=end, total_cells=len(positions), returned=len(records),
                    complete=end == len(positions), budget_exhausted=False, read_elapsed_micros=100,
                    retry_after_ms=50, unknown_cells=sum(c["status"] != "loaded" for c in records), cells=records)
        if not page["complete"]:
            page["next_cursor"] = f"{SCAN}:{end}"
        result.append(page)
    return result


def terrain(**kwargs):
    return Terrain.parse(pages(**kwargs))


def state(inventory=None):
    inventory = {"minecraft:oak_planks": 64, "minecraft:stone_bricks": 64} if inventory is None else inventory
    entries = [dict(slot=i, empty=True, id="", count=0) for i in range(36)]
    for i, (block, count) in enumerate(inventory.items()):
        entries[i] = dict(slot=i, empty=False, id=block, count=count)
    return {"ok": True, "protocol": "mineclient-bridge", "schema_version": 2,
            "world": {"world_generation": WORLD, "dimension": "minecraft:overworld", "game_time": 100},
            "player": {"dimension": "minecraft:overworld", "gamemode": "survival", "x": -2.5, "y": 64.,
                       "z": -2.5, "inventory_total": 36, "inventory_truncated": False, "inventory": entries},
            "nearby": {"radius": 16., "total": 0, "returned": 0, "truncated": False, "entities": []}}


def blueprint(template="floor", width=3, extent=3, origin=Pos(0, 64, 0), pattern="solid", axis="x"):
    high = origin.offset(x=width - 1 if template == "floor" or axis == "x" else 0,
                         y=extent - 1 if template == "wall" else 0,
                         z=extent - 1 if template == "floor" else width - 1 if axis == "z" else 0)
    return Blueprint.parse({"schema_version": 1, "template": template, "origin": origin.json(),
                            "region": {"min": origin.json(), "max": high.json()},
                            "size": {"width": width, "extent": extent}, "axis": axis,
                            "palette": {"primary": "minecraft:oak_planks", "accent": "minecraft:stone_bricks"},
                            "pattern": pattern})
