"""Small bounded blueprint vocabulary; no arbitrary commands or game actions."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math


class PlanError(ValueError):
    pass


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise PlanError("invalid_integer")
    return value


def number(value):
    if type(value) not in (int, float):
        raise PlanError("invalid_number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise PlanError("invalid_number") from None
    if not math.isfinite(result):
        raise PlanError("invalid_number")
    return result


PALETTE = frozenset("minecraft:" + name for name in (
    "stone", "cobblestone", "cobbled_deepslate", "andesite", "diorite", "granite",
    "sandstone", "smooth_stone", "bricks", "stone_bricks", "oak_planks",
    "spruce_planks", "birch_planks", "jungle_planks", "acacia_planks",
    "dark_oak_planks", "mangrove_planks", "cherry_planks",
))
SUPPORT_IDS = PALETTE | {"minecraft:dirt", "minecraft:grass_block", "minecraft:deepslate"}
AIR_IDS = frozenset({"minecraft:air", "minecraft:cave_air", "minecraft:void_air"})
MAX_BLOCKS = 512


@dataclass(frozen=True, order=True)
class Pos:
    x: int
    y: int
    z: int

    def __post_init__(self):
        integer(self.x, -29_999_984, 29_999_984)
        integer(self.y, -1000, 1000)  # Reads may include out-of-world cells.
        integer(self.z, -29_999_984, 29_999_984)

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict) or not all(k in data for k in ("x", "y", "z")):
            raise PlanError("invalid_position")
        return cls(data["x"], data["y"], data["z"])

    def offset(self, x=0, y=0, z=0):
        return Pos(self.x + x, self.y + y, self.z + z)

    def json(self):
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass(frozen=True)
class Region:
    minimum: Pos
    maximum: Pos

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict) or set(data) != {"min", "max"}:
            raise PlanError("explicit_region_required")
        low, high = Pos.parse(data["min"]), Pos.parse(data["max"])
        integer(low.y, -64, 319)
        integer(high.y, -64, 319)
        for a, b in zip((low.x, low.y, low.z), (high.x, high.y, high.z)):
            integer(b - a, 0, 63)
        return cls(low, high)

    def contains(self, pos):
        return (self.minimum.x <= pos.x <= self.maximum.x
                and self.minimum.y <= pos.y <= self.maximum.y
                and self.minimum.z <= pos.z <= self.maximum.z)

    def json(self):
        return {"min": self.minimum.json(), "max": self.maximum.json()}


@dataclass(frozen=True)
class Blueprint:
    template: str
    origin: Pos
    region: Region
    width: int
    extent: int
    axis: str
    primary: str
    accent: str
    pattern: str

    @classmethod
    def parse(cls, spec):
        if not isinstance(spec, dict) or set(spec) != {
            "schema_version", "template", "origin", "region", "size", "axis", "palette", "pattern"
        } or type(spec.get("schema_version")) is not int or spec["schema_version"] != 1:
            raise PlanError("invalid_blueprint_schema")
        template = spec["template"]
        if template not in ("floor", "wall"):
            raise PlanError("unsupported_template")
        origin, region = Pos.parse(spec["origin"]), Region.parse(spec["region"])
        size, palette = spec["size"], spec["palette"]
        if not isinstance(size, dict) or set(size) != {"width", "extent"}:
            raise PlanError("invalid_size")
        width, extent = integer(size["width"], 1, 32), integer(size["extent"], 1, 32)
        if width * extent > MAX_BLOCKS:
            raise PlanError("blueprint_block_budget_exceeded")
        if not isinstance(palette, dict) or set(palette) != {"primary", "accent"}:
            raise PlanError("invalid_palette")
        if any(type(v) is not str or v not in PALETTE for v in palette.values()):
            raise PlanError("unsupported_palette_block")
        if spec["pattern"] not in ("solid", "checker", "frame"):
            raise PlanError("unsupported_pattern")
        if spec["axis"] not in ("x", "z") or (template == "floor" and spec["axis"] != "x"):
            raise PlanError("unsupported_axis")
        result = cls(template, origin, region, width, extent, spec["axis"],
                     palette["primary"], palette["accent"], spec["pattern"])
        if any(not region.contains(pos) for pos, _ in result.cells()):
            raise PlanError("blueprint_outside_explicit_region")
        return result

    def cells(self):
        result = []
        for v in range(self.extent):
            for u in range(self.width):
                if self.template == "floor":
                    pos = self.origin.offset(x=u, z=v)
                elif self.axis == "x":
                    pos = self.origin.offset(x=u, y=v)
                else:
                    pos = self.origin.offset(z=u, y=v)
                accent = ((self.pattern == "checker" and (u + v) % 2 == 1)
                          or (self.pattern == "frame" and (u in (0, self.width - 1)
                                                          or v in (0, self.extent - 1))))
                result.append((pos, self.accent if accent else self.primary))
        return tuple(result)

    def spec(self):
        return {"schema_version": 1, "template": self.template, "origin": self.origin.json(),
                "region": self.region.json(), "size": {"width": self.width, "extent": self.extent},
                "axis": self.axis, "palette": {"primary": self.primary, "accent": self.accent},
                "pattern": self.pattern}

    def preview(self):
        cells = self.cells()
        symbols = {self.primary: "P"}
        if self.accent != self.primary:
            symbols[self.accent] = "A"
        rows = ["".join(symbols[block] for _, block in cells[i:i+self.width])
                for i in range(0, len(cells), self.width)]
        if self.template == "wall":
            rows.reverse()
        return {"format": "building-blueprint-v1", "blueprint": self.spec(),
                "provisional": True, "executable": False,
                "material_totals": dict(sorted(Counter(b for _, b in cells).items())),
                "preview": {"view": "top (+z downward)" if self.template == "floor" else "front (+y upward)",
                            "horizontal_axis": "+x" if self.template == "floor" else "+" + self.axis,
                            "legend": {symbol: block for block, symbol in symbols.items()}, "rows": rows},
                "cells": [{"position": pos.json(), "block": block} for pos, block in cells]}
