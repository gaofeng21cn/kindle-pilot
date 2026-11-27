from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kindle_companion.cli import main


ROOT = Path(__file__).resolve().parents[1]


class SoftwareInfoTests(unittest.TestCase):
    def test_software_readback_does_not_probe_device_or_read_task(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "private-task.json"
            state.write_text('{"private": "must-not-appear"}')
            with patch("kindle_companion.cli.discover", side_effect=AssertionError("device access")), \
                    patch("kindle_companion.cli.load_state", side_effect=AssertionError("task access")), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(main(["--state", str(state), "--json", "software-info"]), 0)
        result = json.loads(output.getvalue())
        manifest = json.loads((ROOT / "opl-package.json").read_text(encoding="utf-8"))
        identity = manifest["identity"]
        self.assertEqual(result["package_id"], identity["id"])
        self.assertEqual(result["display_name"], identity["name"]["en-US"])
        self.assertEqual(result["description"], identity["summary"]["en-US"])
        self.assertEqual(result["version"], identity["version"])
        self.assertEqual(result["manifest_version"], identity["version"])
        self.assertEqual(result["source_repo"], identity["repository"])
        self.assertEqual(result["core_module_ids"], manifest["provides"]["module_ids"])
        self.assertEqual(result["management_owner"], "opl_framework")
        self.assertIsNone(result["plugin_selector"])
        self.assertIsNone(result["publication_channel_admission"])
        self.assertEqual(result["device_status"], "not_checked")
        self.assertNotIn("must-not-appear", output.getvalue())


if __name__ == "__main__":
    unittest.main()
