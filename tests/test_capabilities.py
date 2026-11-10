from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kindle_companion.capabilities import capability_info, load_capability_catalog
from kindle_companion.cli import main
from kindle_companion.models import CompanionError


ROOT = Path(__file__).resolve().parents[1]


class CapabilityCatalogTests(unittest.TestCase):
    def test_catalog_matches_package_exports_without_device_or_task_access(self):
        with patch("kindle_companion.cli.discover", side_effect=AssertionError("device access")), \
                patch("kindle_companion.cli.load_state", side_effect=AssertionError("task access")):
            result = capability_info(ROOT)
        package = json.loads((ROOT / "opl-package.json").read_text())
        ids = [module["id"] for module in result["modules"]]
        self.assertEqual(ids, package["exports"]["core_module_ids"])
        self.assertEqual(result["capability_abi"], package["capability_abi"])
        self.assertEqual(result["device_status"], "not_checked")
        self.assertEqual(result["account_status"], "human_confirmation_required")

    def test_cli_capabilities_is_a_stable_json_discovery_surface(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--json", "capabilities"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["schema"], "kindle-pilot-capability-catalog/v1")
        self.assertIn("kindle.wireless.maintenance.v1", [module["id"] for module in result["modules"]])

    def test_catalog_rejects_export_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in ("opl-package.json", "capabilities/kindle-pilot.json"):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            package = json.loads((root / "opl-package.json").read_text())
            package["exports"]["core_module_ids"] = ["drifted"]
            (root / "opl-package.json").write_text(json.dumps(package))
            with self.assertRaises(CompanionError) as raised:
                load_capability_catalog(root)
            self.assertEqual(raised.exception.code, "CAPABILITY_EXPORT_MISMATCH")


if __name__ == "__main__":
    unittest.main()
