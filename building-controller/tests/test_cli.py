import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from building_controller.__main__ import main
from .helpers import blueprint, pages, state


class CLITests(unittest.TestCase):
    def invoke(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_blueprint_cli_preview(self):
        code, out, err = self.invoke(["blueprint", "--template", "floor", "--origin", "0", "64", "0",
                                     "--region-min", "0", "64", "0", "--region-max", "2", "64", "2",
                                     "--width", "3", "--extent", "3", "--pattern", "frame"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out)["preview"]["rows"], ["AAA", "APA", "AAA"])

    def files(self, root, inventory=None):
        for name, data in (("blueprint", blueprint().preview()), ("terrain", pages()), ("state", state(inventory))):
            (root / (name + ".json")).write_text(json.dumps(data))
        return ["plan", "--blueprint", str(root / "blueprint.json"), "--terrain", str(root / "terrain.json"),
                "--state", str(root / "state.json")]

    def test_plan_cli_success(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.files(Path(temp))
            code, out, err = self.invoke(args)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "provisional_plan")
        self.assertEqual(err, "")

    def test_plan_cli_blocked_exit_three(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.files(Path(temp), {})
            code, out, err = self.invoke(args)
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["proposed_placements"], [])
        self.assertEqual(err, "")

    def test_capture_key_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "b.json").write_text(json.dumps(blueprint().spec()))
            (root / "c.json").write_text(json.dumps({"cube": pages(), "state_after": state()}))
            code, out, err = self.invoke(["plan", "--blueprint", str(root / "b.json"),
                                         "--terrain", str(root / "c.json"), "--terrain-key", "cube",
                                         "--state-key", "state_after"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "provisional_plan")

    def test_output_is_exclusive_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = self.files(root)
            output = root / "existing.json"
            output.write_text("keep")
            code, out, err = self.invoke(args + ["--output", str(output)])
            self.assertEqual(output.read_text(), "keep")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["status"], "invalid_input")

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = self.files(root)
            (root / "blueprint.json").write_text('{"schema_version":1,"schema_version":2}')
            code, out, err = self.invoke(args)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["error"], "duplicate_json_key")

    def test_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = self.files(root)
            (root / "state.json").write_text('{"x":NaN}')
            code, out, err = self.invoke(args)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["error"], "nonfinite_json_number")


if __name__ == "__main__":
    unittest.main()
