"""Resolve all production modules and shared fixtures from this checkout."""
import importlib.util
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
JAVA_ROOT = REPO_ROOT / 'client-mod/src/main/java/io/github/campione01/mineclientbridge'
PARTS = ('capability-runtime', 'resident-controller', 'navigation-controller',
         'navigation-cursor', 'defense-watchdog', 'gameplay-helpers',
         'building-controller', 'external-controller', 'multiagent-coordination')
SOURCE_PATHS = tuple(REPO_ROOT / name for name in PARTS)
TEST_PATHS = (REPO_ROOT / 'capability-runtime/tests',
              REPO_ROOT / 'resident-controller/tests')


def configure_source_paths():
    """Prefer the combined checkout, never a sibling extension's source tree."""
    paths = [str(path) for path in (*TEST_PATHS, *SOURCE_PATHS)]
    missing = [path for path in paths if not Path(path).is_dir()]
    if missing:
        raise RuntimeError('Missing checkout directories: ' + ', '.join(missing))
    sys.path[:] = paths + [path for path in sys.path if path not in paths]
    sys.dont_write_bytecode = True
    os.environ['WATCHDOG_CANDIDATE'] = str(REPO_ROOT / 'defense-watchdog')


def load_owner_fixture():
    """Share the unchanged mainline harness without importing a stale baseline."""
    name = 'mining_collect._main_owner_fixture'
    path = TEST_PATHS[0] / 'test_capability_ownership.py'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError('Cannot load current owner-chain fixture')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    module = sys.modules[name]
    if Path(module.__file__).resolve() != path.resolve():
        raise ImportError('Owner-chain fixture escaped the current checkout')
    return module
