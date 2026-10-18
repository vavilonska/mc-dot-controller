"""Resolve shipped source siblings for explicit standalone entrypoints only."""
from pathlib import Path
import sys


def configure_source_dependencies():
    # Resolve relative to this delivered package, never the working directory or
    # an operator-supplied ambient PYTHONPATH. Importing this module has no I/O.
    root = Path(__file__).resolve().parents[2]
    for name in ("navigation-controller", "minecraft-navigation-controller"):
        candidate = root / name
        if (candidate / "navigation_controller" / "observation_clock.py").is_file():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
            return candidate
    raise RuntimeError("delivered_navigation_controller_dependency_missing")
