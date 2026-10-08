"""Focused fake-only portability checks; no live mailbox or game access."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import resident_controller.ipc


HELPERS = Path(__file__).resolve().parents[1]


class FakeClient:
    def __init__(self, result):
        self.result = result
        self.commands = []
        self.waits = []

    def submit(self, command):
        self.commands.append(command)
        return "offline-request"

    def wait(self, request, timeout):
        self.waits.append((request, timeout))
        return self.result


class PortabilityChecks(unittest.TestCase):
    def test_imports_do_not_construct_clients_or_write_files(self):
        # Import-source reads are allowed; runtime writes and client creation are not.
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(resident_controller.ipc, "QueueClient",
                                             side_effect=AssertionError("client created")))
            for method in ("mkdir", "write_text", "write_bytes", "replace", "rename"):
                stack.enter_context(patch.object(Path, method,
                                                 side_effect=AssertionError("file write")))
            for name in ("crafting_helper", "play", "export_dashboard_state"):
                module = importlib.import_module(name)
                importlib.reload(module)

    def test_play_requires_configuration_and_uses_only_supplied_client(self):
        play = importlib.import_module("play")
        play.configure(None)
        self.addCleanup(play.configure, None)
        with self.assertRaisesRegex(RuntimeError, "configure_a_queue_client"):
            play.obs()
        client = FakeClient({"status": "succeeded", "result": {"state": "offline"}})
        play.configure(client)
        self.assertEqual(client.commands, [])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(play.obs(radius=3), {"state": "offline"})
        self.assertEqual(client.commands, [{"op": "observe", "terrain": True,
                                           "radius": 3, "vertical": 4}])
        self.assertEqual(client.waits, [("offline-request", 30)])

    def test_pure_path_helper_needs_no_client(self):
        play = importlib.import_module("play")
        play.configure(None)
        cells = []
        for x in range(3):
            for y in range(3):
                cells.append({"x": x, "y": y, "z": 0,
                              "collision_empty": y > 0,
                              "fluid": "minecraft:empty", "hazards": [],
                              "full_top_support": y == 0})
        observation = {"terrain": {"cells": cells},
                       "state": {"player": {"x": 0.5, "y": 1, "z": 0.5}}}
        self.assertEqual(play.path(observation, (2, 1, 0)), [
            {"x": 1.5, "y": 1, "z": 0.5, "jump": False},
            {"x": 2.5, "y": 1, "z": 0.5, "jump": False}])

    def test_export_uses_explicit_output_directory(self):
        exporter = importlib.import_module("export_dashboard_state")
        client = FakeClient({"status": "succeeded", "finished_at": 0,
                             "result": {"status": {"in_world": True},
                                        "state": {"player": {"name": "offline-player",
                                                             "x": 0, "y": 1, "z": 0}}}})
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "private-output"
            self.assertTrue(exporter.once(client, output))
            self.assertEqual(sorted(path.name for path in output.iterdir()), ["state.json"])
            snapshot = json.loads((output / "state.json").read_text())
            self.assertEqual(snapshot["player_name"], "offline-player")
            self.assertEqual(snapshot["position"], {"x": 0, "y": 1, "z": 0})
        self.assertEqual(client.commands, [{"op": "observe"}])
        self.assertEqual(client.waits, [("offline-request", 15)])

    def test_export_failure_does_not_write(self):
        exporter = importlib.import_module("export_dashboard_state")
        client = FakeClient({"status": "pending"})
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "private-output"
            self.assertFalse(exporter.once(client, output))
            self.assertFalse(output.exists())

    def test_cli_help_and_required_paths_work_from_another_directory(self):
        # No PYTHONPATH or resident package is needed for help/argument validation.
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        environment.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as temporary:
            for arguments, code in ((["--help"], 0), ([], 2), (["--once"], 2)):
                result = subprocess.run(
                    [sys.executable, "-B", str(HELPERS / "export_dashboard_state.py"),
                     *arguments], cwd=temporary, env=environment, capture_output=True,
                    text=True, timeout=10, check=False)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertIn("--queue", result.stdout + result.stderr)
                self.assertIn("--output-dir", result.stdout + result.stderr)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_cli_finds_sibling_client_in_relocated_checkout(self):
        # The temporary sibling is a fake client, not a mailbox implementation.
        fake_source = '''
class QueueClient:
    def __init__(self, directory):
        assert directory.name == "offline-mailbox"
        assert not directory.exists()
    def submit(self, command):
        assert command == {"op": "observe"}
        return "offline-request"
    def wait(self, request, timeout):
        assert (request, timeout) == ("offline-request", 15)
        return {"status": "succeeded", "finished_at": 0,
                "result": {"status": {"in_world": False}, "state": {}}}
'''
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        environment.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "relocated checkout" / "gameplay-helpers" / "export_dashboard_state.py"
            package = script.parent.parent / "resident-controller" / "resident_controller"
            script.parent.mkdir(parents=True)
            package.mkdir(parents=True)
            script.write_bytes((HELPERS / "export_dashboard_state.py").read_bytes())
            (package / "__init__.py").write_text("")
            (package / "ipc.py").write_text(fake_source)
            output = root / "private-output"
            mailbox = root / "offline-mailbox"
            result = subprocess.run(
                [sys.executable, "-B", str(script), "--once", "--queue", str(mailbox),
                 "--output-dir", str(output)], cwd=root, env=environment,
                capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "state.json").is_file())
            self.assertFalse(mailbox.exists())


if __name__ == "__main__":
    unittest.main()
