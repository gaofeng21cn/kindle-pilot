from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from kindle_companion.collections import KCAdapter, inventory, series_name, write_new
from kindle_companion.manifest import load_manifest
from kindle_companion.models import CompanionError


ROOT = Path(__file__).resolve().parents[1]


def snapshot() -> dict:
    def book(uid: str, name: str, count: int, location: str | None) -> dict:
        return dict(uuid=uid, title=name, location=location, cde_key=uid, cde_type="PDOC",
                    collection_count=count, calibre_uuid=None, metadata_matches=0)
    return dict(
        schema="kc-bookshelf-export/v2", snapshot_id="fixture-snapshot", generated_utc="2026-11-10T00:00:00Z",
        device=dict(instance_id="fixture-device", storage_uuid=None, serial_sha256=None),
        firmware="Kindle 5.20.1.0.2 (fixture)",
        capabilities=dict(version="fixture-readonly", verified_operations=["verify_state"], evidence="synthetic fixture only"),
        policy=dict(version=1, protected_collections=[], max_members=350, max_request_bytes=262144, max_creates=50, max_rename_delete=10),
        mapping=dict(stable=False, calibre_library_uuid=None, metadata_sha256=""),
        books=[book("b0", "示例漫畫 - 卷01", 0, "/mnt/us/documents/Downloads/Items01/示例漫畫 - 卷01.azw3"),
               book("b1", "示例漫畫 - 話001-005", 0, "/mnt/us/documents/Downloads/Items01/示例漫畫 - 話001-005.kfx"),
               book("cloud", "示例漫畫 - 卷02", None, None),
               book("script", "launcher", 0, "/mnt/us/documents/launcher.sh")],
        collections=[dict(uuid="existing", name="保留原架", complete=True)], relations=[],
    )


class InventoryTests(unittest.TestCase):
    def test_series_parsing_preserves_title_hyphen_and_split_volume(self):
        self.assertEqual(series_name("/mnt/us/documents/A - B - 第20卷[2]_" + "A" * 32 + ".azw3"), "A - B")
        self.assertEqual(series_name("/mnt/us/documents/示例漫畫 - 話005.5-010.kfx"), "示例漫畫")
        self.assertIsNone(series_name("/mnt/us/documents/独立作品.azw3"))

    def test_inventory_uses_local_indexed_books_and_reports_count_mismatch(self):
        s = snapshot()
        s["relations"] = [dict(book_uuid="b1")]
        report = inventory(s, "/mnt/us/documents/Downloads/Items01")
        self.assertEqual(len(report["series"]), 1)
        self.assertEqual({b["uuid"] for b in report["series"][0]["books"]}, {"b0", "b1"})
        by_id = {b["uuid"]: b for b in report["series"][0]["books"]}
        self.assertFalse(by_id["b1"]["counts_consistent"])
        self.assertTrue(by_id["b0"]["counts_consistent"])

    def test_scope_traversal_is_rejected(self):
        with self.assertRaises(CompanionError):
            inventory(snapshot(), "/mnt/us/documents/../")

    def test_preparation_never_replaces_changed_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "job.json"
            write_new(path, b"original")
            write_new(path, b"original")
            with self.assertRaises(CompanionError):
                write_new(path, b"changed")
            self.assertEqual(path.read_bytes(), b"original")


@unittest.skipUnless(os.environ.get("KINDLE_KC_ARCHIVE"), "set KINDLE_KC_ARCHIVE to the manifest-pinned upstream release")
class KCIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.archive = Path(os.environ["KINDLE_KC_ARCHIVE"])
        self.route = load_manifest(ROOT / "manifests/compatibility.json").routes[0]
        self.adapter = KCAdapter(self.archive, self.route)
        self.snapshot = snapshot()
        self.adapter.protocol.validate(self.snapshot)

    def test_hash_mismatch_blocks_import_and_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "fake.zip"
            other.write_bytes(b"not the upstream release")
            with self.assertRaises(CompanionError) as raised:
                KCAdapter(other, self.route)
            self.assertEqual(raised.exception.code, "COLLECTION_ARCHIVE_HASH")

    def test_wrong_firmware_is_rejected_before_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            s = copy.deepcopy(self.snapshot); s["firmware"] = "Kindle 5.20.2"
            path.write_text(json.dumps(s))
            with self.assertRaises(CompanionError) as raised:
                self.adapter.snapshot(path)
            self.assertEqual(raised.exception.code, "COLLECTION_FIRMWARE")

    def test_probe_preserves_upstream_guard_and_ready_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.adapter.prepare_probe(self.snapshot, "b0", Path(tmp))
            payload = Path(result["paths"][0]).read_bytes()
            marker = Path(result["paths"][1]).read_text()
            self.assertEqual(marker, hashlib.sha256(payload).hexdigest() + " probe\n")
            request = self.adapter.protocol.loads(payload)
            self.assertEqual(len(request["operations"]), 6)
            self.assertEqual(len({o["collection_uuid"] for o in request["operations"]}), 1)
            self.assertEqual(result["book_uuid"], "b0")
            with self.assertRaises(CompanionError):
                self.adapter.prepare_probe(self.snapshot, "cloud", Path(tmp) / "bad")

    def test_unverified_route_cannot_generate_edit_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checker = root / "checker"; checker.write_bytes(b"test ELF placeholder")
            config = copy.deepcopy(self.route.native_collections)
            config["checker_build"]["artifact_sha256"] = hashlib.sha256(checker.read_bytes()).hexdigest()
            config["status"] = "blocked"
            adapter = KCAdapter(self.archive, replace(self.route, native_collections=config))
            result = adapter.stage(checker, root / "stage")
            self.assertEqual(result["modes"], ["check", "probe"])
            self.assertFalse((root / "stage/documents/KindlePilot-Collections-Apply.sh").exists())
            runtime = root / "stage/kc-sync/runtime" / config["runtime_id"]
            self.assertEqual((runtime / "kc-backup-check").read_bytes(), checker.read_bytes())
            self.assertIn("readonly", (runtime / "refresh.sh").read_text())

    def test_unverified_route_blocks_direct_edit_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CompanionError) as raised:
                self.adapter.launcher({}, "edit")
            self.assertEqual(raised.exception.code, "COLLECTION_UNVERIFIED")
            request = self.adapter.probe.prepare_probe(self.snapshot, "b0", "fixture-library")
            with self.assertRaises(CompanionError) as raised:
                self.adapter.queue(request, "edit", Path(tmp))
            self.assertEqual(raised.exception.code, "COLLECTION_UNVERIFIED")
            self.assertFalse(list(Path(tmp).iterdir()))

    def test_series_plan_keeps_existing_collections_and_blocks_unverified_route(self):
        value = self.adapter.plan_series(self.snapshot, "/mnt/us/documents/Downloads/Items01", "漫画｜", ["示例漫畫"])
        self.assertIn("ROUTE_NOT_VERIFIED", {b["code"] for b in value["blockers"]})
        self.assertEqual({o["kind"] for o in value["operations"]}, {"create_collection", "add_members"})
        self.assertTrue(all(o["collection_uuid"] != "existing" for o in value["operations"]))

    def test_confirmed_receipt_does_not_prove_durable_state(self):
        request = self.adapter.probe.prepare_probe(self.snapshot, "b0", "fixture-library")
        result = self.adapter.protocol.seal(dict(
            schema="kc-edit-result/v1", job_id=request["job_id"], request_digest=request["request_digest"],
            device=request["device"], snapshot_id=None,
            operations=[dict(op_id=o["op_id"], status="confirmed", observed_digest=o["after"], message="synthetic")
                        for o in request["operations"]]), "result_digest")
        current = copy.deepcopy(self.snapshot)
        cid = request["operations"][0]["collection_uuid"]
        current["collections"].append(dict(uuid=cid, name="remaining test collection", complete=True))
        with tempfile.TemporaryDirectory() as tmp:
            req, res = Path(tmp) / "request.json", Path(tmp) / "result.json"
            req.write_bytes(self.adapter.protocol.canonical(request)); res.write_bytes(self.adapter.protocol.canonical(result))
            verdict = self.adapter.receipt(req, res, current)
            self.assertTrue(verdict["all_operations_confirmed"])
            self.assertFalse(verdict["verified"])
            current["collections"] = self.snapshot["collections"]
            self.assertFalse(self.adapter.receipt(req, res, current)["verified"])
            current["snapshot_id"] = "fixture-after-probe"
            current["generated_utc"] = "2026-11-10T00:01:00Z"
            self.assertTrue(self.adapter.receipt(req, res, current)["verified"])
            current["books"][0]["collection_count"] = 1
            verdict = self.adapter.receipt(req, res, current)
            self.assertFalse(verdict["verified"])
            self.assertFalse(verdict["book_counts"][0]["matches"])


if __name__ == "__main__":
    unittest.main()
