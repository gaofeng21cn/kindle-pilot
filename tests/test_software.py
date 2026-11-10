from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kindle_companion.cli import main


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
        self.assertEqual(result["package_id"], "kindle-pilot")
        self.assertEqual(result["display_name"], "Kindle Pilot")
        self.assertEqual(result["version"], result["manifest_version"])
        self.assertEqual(result["device_status"], "not_checked")
        self.assertNotIn("must-not-appear", output.getvalue())


if __name__ == "__main__":
    unittest.main()
