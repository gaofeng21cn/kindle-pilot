from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from kindle_companion.compat import compare_versions, decide_route, product_code
from kindle_companion.discovery import discover
from kindle_companion.manifest import load_manifest
from kindle_companion.models import CompanionError, DeviceIdentity
from kindle_companion.mtp import MtpClient, parse_storage_info, quote_batch_arg
from kindle_companion.state import load_state, record_step, save_state
from kindle_companion.verify import verify_asset


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = load_manifest(ROOT / "manifests" / "compatibility.json")


class CompanionTests(unittest.TestCase):
    def test_version_comparison_handles_trailing_zero(self) -> None:
        self.assertEqual(compare_versions("5.20.1", "5.20.1.0.2"), -1)
        self.assertEqual(compare_versions("5.20.1.0.2", "5.20.1.0.2"), 0)

    def test_colorsoft_route_is_exact(self) -> None:
        self.assertEqual(product_code("Kindle Colorsoft Signature Edition"), "CS")
        decision = decide_route(
            MANIFEST,
            DeviceIdentity("Kindle Colorsoft Signature Edition", "TESTSERIAL0001"),
            "5.20.1.0.2",
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.route.id, "vera-cs-5.20.1.0.2")

    def test_unknown_firmware_is_rejected(self) -> None:
        decision = decide_route(
            MANIFEST,
            DeviceIdentity("Kindle Colorsoft Signature Edition", "serial"),
            "5.20.2",
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "FIRMWARE_UNSUPPORTED")

    def test_discovery_parses_macos_output(self) -> None:
        product = "Kindle Colorsoft Signature Edition TESTSERIAL0001"
        ioreg = '"USB Serial Number" = "TESTSERIAL0001"'
        identity = discover(product_output=product, ioreg_output=ioreg)
        self.assertEqual(identity.product, "Kindle Colorsoft Signature Edition")
        self.assertEqual(identity.serial, "TESTSERIAL0001")

    def test_discovery_reports_missing_device(self) -> None:
        with self.assertRaises(CompanionError) as raised:
            discover(product_output="", ioreg_output="")
        self.assertEqual(raised.exception.code, "DEVICE_NOT_FOUND")

    def test_storage_info_parser(self) -> None:
        parsed = parse_storage_info(
            "used 13503012864 (49%), free 13568237568 bytes of 27071250432"
        )
        self.assertEqual(parsed["free_bytes"], 13568237568)

    def test_mtp_marks_transfer_error_even_when_exit_zero(self) -> None:
        completed = Mock(returncode=0, stdout="error: SendObjectInfo: StoreFull", stderr="")
        runner = Mock(return_value=completed)
        with tempfile.TemporaryDirectory() as directory:
            client = MtpClient(Path("/tmp/mtp-cli"), runner=runner)
            with self.assertRaises(CompanionError) as raised:
                client.run(("storage-info 65537", "exit"))
        self.assertEqual(raised.exception.code, "MTP_TRANSFER_FAILED")

    def test_mtp_quotes_paths_with_spaces(self) -> None:
        self.assertEqual(quote_batch_arg("/tmp/My Kindle/file.bin"), '"/tmp/My Kindle/file.bin"')

    def test_state_requires_confirmation_for_manual_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = load_state(path)
            with self.assertRaises(CompanionError) as raised:
                record_step(state, "trigger_jailbreak", "done")
            self.assertEqual(raised.exception.code, "CONFIRMATION_REQUIRED")
            state["device"] = {"product": "Kindle Colorsoft Signature Edition", "serial": "serial"}
            state["route_status"] = "supported"
            record_step(state, "download_assets", "done", "sha256 verified")
            record_step(state, "transfer_assets", "done", "remote byte-size readback")
            record_step(state, "font_calibration", "done", "user observed", confirmed=True)
            record_step(state, "trigger_jailbreak", "done", "JAILBROKEN visible", confirmed=True)
            save_state(path, state)
            self.assertEqual(load_state(path)["steps"]["trigger_jailbreak"]["status"], "done")

    def test_asset_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.bin"
            path.write_bytes(b"kindle")
            result = verify_asset(
                path,
                "a26c2f2e3b4a7bca8c0a8c6b2b1d6a4f1ec4a1b8c9b0a3d3f6b5f8a2bb6e7ce1",
            )
            self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
