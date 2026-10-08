"""Offline CLI. Reads local JSON files only; no transport, credentials or input APIs."""
import argparse
import json
from pathlib import Path
import sys

from .model import Blueprint, PALETTE, PlanError
from .planner import plan
from .terrain import Terrain


def position(values):
    return dict(zip(("x", "y", "z"), values))


def load(path):
    path = Path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise PlanError("input_file_too_large")
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PlanError("duplicate_json_key")
            result[key] = value
        return result
    def no_constant(value):
        raise PlanError("nonfinite_json_number")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates,
                      parse_constant=no_constant)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline-only floor/wall blueprint and construction planner")
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("blueprint", help="Preview bounded floor/wall template and material totals")
    make.add_argument("--template", choices=("floor", "wall"), required=True)
    make.add_argument("--origin", nargs=3, type=int, required=True, metavar=("X", "Y", "Z"))
    make.add_argument("--region-min", nargs=3, type=int, required=True, metavar=("X", "Y", "Z"))
    make.add_argument("--region-max", nargs=3, type=int, required=True, metavar=("X", "Y", "Z"))
    make.add_argument("--width", type=int, required=True)
    make.add_argument("--extent", type=int, required=True, help="Floor depth or wall height")
    make.add_argument("--axis", choices=("x", "z"), default="x", help="Wall width direction; floor must use x")
    make.add_argument("--primary", choices=sorted(PALETTE), default="minecraft:oak_planks")
    make.add_argument("--accent", choices=sorted(PALETTE), default="minecraft:stone_bricks")
    make.add_argument("--pattern", choices=("solid", "checker", "frame"), default="solid")
    make.add_argument("--output", help="Write a new JSON file; never overwrite an existing file")
    check = commands.add_parser("plan", help="Compare a blueprint against captured terrain/state JSON")
    check.add_argument("--blueprint", required=True)
    check.add_argument("--terrain", required=True)
    check.add_argument("--terrain-key", help="Explicit top-level group in a capture, e.g. cube")
    check.add_argument("--state", help="Optional separate file; otherwise state may be selected from terrain file")
    check.add_argument("--state-key", help="Explicit state group, e.g. state_after")
    check.add_argument("--output", help="Write a new JSON file; never overwrite an existing file")
    args = parser.parse_args(argv)
    try:
        if args.command == "blueprint":
            spec = {"schema_version": 1, "template": args.template, "origin": position(args.origin),
                    "region": {"min": position(args.region_min), "max": position(args.region_max)},
                    "size": {"width": args.width, "extent": args.extent}, "axis": args.axis,
                    "palette": {"primary": args.primary, "accent": args.accent}, "pattern": args.pattern}
            output = Blueprint.parse(spec).preview()
        else:
            blueprint_data = load(args.blueprint)
            if not isinstance(blueprint_data, dict):
                raise PlanError("invalid_blueprint_file")
            blueprint = Blueprint.parse(blueprint_data.get("blueprint", blueprint_data))
            capture = load(args.terrain)
            pages = capture[args.terrain_key] if args.terrain_key else capture
            state = load(args.state) if args.state else capture if args.state_key else None
            if args.state_key:
                state = state[args.state_key]
            output = plan(blueprint, Terrain.parse(pages), state)
        rendered = json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            with Path(args.output).open("x", encoding="utf-8") as destination:
                destination.write(rendered)
        else:
            sys.stdout.write(rendered)
        return 3 if output.get("status") == "blocked" else 0
    except (PlanError, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        # Keep machine-readable failure output and never expose a partial plan.
        error = {"format": "building-error-v1", "status": "invalid_input", "executable": False,
                 "error": str(exc), "proposed_placements": []}
        sys.stderr.write(json.dumps(error, sort_keys=True) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
