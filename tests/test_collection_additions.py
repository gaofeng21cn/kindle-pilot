import copy
import unittest

from kindle_companion.collection_additions import (
    prepare_addition,
    prepare_rename,
    prepare_retirement,
    verify_addition,
    verify_rename,
    verify_retirement,
)
from kindle_companion.models import CompanionError


def catalog():
    return {
        "collections": [{"uuid": "old", "name": "原有隐藏合集", "visible": 0,
                         "member_count": 1, "home_member_count": 1}],
        "books": [{"uuid": "book", "location": "/mnt/us/documents/example.azw3",
                   "archived": 0, "collection_count": 0, "collections": ["old"]}],
        "relations": [{"collection_uuid": "old", "book_uuid": "book", "present": 1}],
    }


TARGET = {"uuid": "new", "name": "漫画｜示例", "book_uuids": ["book"]}


class NativeAdditionsTests(unittest.TestCase):
    def test_hidden_membership_is_preserved_without_scalar_count_repair(self):
        before = catalog()
        plan = prepare_addition(before, TARGET, 100)
        commands = plan["payload"]["commands"]
        self.assertEqual(commands[1]["update"]["collections"], ["new", "old"])
        self.assertEqual(commands[-1]["update"]["members"], ["book"])
        self.assertNotIn("collectionCount", commands[1]["update"])
        self.assertEqual(before, catalog())

    def test_later_membership_loss_fails_acceptance(self):
        before = catalog()
        plan = prepare_addition(before, TARGET, 100)
        after = copy.deepcopy(before)
        after["collections"].append({"uuid": "new", "name": TARGET["name"], "visible": 1,
                                     "member_count": 1, "home_member_count": 1})
        after["relations"].append({"collection_uuid": "new", "book_uuid": "book", "present": 1})
        after["books"][0].update(collection_count=1, collections=["old", "new"])
        self.assertTrue(verify_addition(before, after, plan)["verified"])
        self.assertFalse(prepare_addition(after, TARGET, 200)["payload"]["commands"])
        after["relations"] = after["relations"][:1]
        self.assertFalse(verify_addition(before, after, plan)["verified"])

    def test_duplicate_name_and_missing_local_identity_stop_preparation(self):
        with self.assertRaises(CompanionError):
            prepare_addition(catalog(), dict(TARGET, name="原有隐藏合集"), 100)
        before = catalog()
        before["books"][0]["location"] = None
        with self.assertRaises(CompanionError):
            prepare_addition(before, TARGET, 100)

    def test_adding_to_existing_collection_keeps_cloud_members(self):
        before = catalog()
        before["books"].append({"uuid": "cloud", "location": None, "archived": 1,
                                "collection_count": 0, "collections": ["old"]})
        before["relations"].append({"collection_uuid": "old", "book_uuid": "cloud", "present": 0})
        before["books"].append({"uuid": "local", "location": "/mnt/us/documents/new.kfx",
                                "archived": 0, "collection_count": 0, "collections": []})
        target = {"uuid": "old", "name": "原有隐藏合集", "book_uuids": ["local"]}
        prepared = prepare_addition(before, target, 100)
        self.assertFalse(prepared["created"])
        self.assertEqual(prepared["payload"]["commands"][-1]["update"]["members"], ["book", "cloud", "local"])

    def test_retirement_requires_exact_task_owned_collection_and_destination(self):
        before = catalog()
        before["collections"].append({"uuid": "new", "name": "漫画｜示例", "visible": 1,
                                       "member_count": 1, "home_member_count": 1})
        before["relations"].append({"collection_uuid": "new", "book_uuid": "book", "present": 1})
        before["books"][0]["collections"].append("new")
        before["books"][0]["collection_count"] = 1
        target = {"uuid": "old", "name": "原有隐藏合集", "member_uuids": ["book"]}
        prepared = prepare_retirement(before, target, set(), {"book": {"old", "new"}})
        self.assertEqual(prepared["payload"]["commands"][-1], {"delete": {"uuid": "old"}})
        after = copy.deepcopy(before)
        after["collections"] = [c for c in after["collections"] if c["uuid"] != "old"]
        after["relations"] = [r for r in after["relations"] if r["collection_uuid"] != "old"]
        after["books"][0]["collections"] = ["new"]
        self.assertTrue(verify_retirement(before, after, prepared)["verified"])
        with self.assertRaises(CompanionError):
            prepare_retirement(before, target, {"old"}, {"book": {"old", "new"}})

    def test_rename_is_compare_and_swap_and_preserves_graph(self):
        before = catalog()
        target = {"uuid": "old", "current_name": "原有隐藏合集", "name": "图书｜历史"}
        prepared = prepare_rename(before, target)
        self.assertEqual(prepared["payload"]["commands"][0]["update"]["titles"][0]["display"], "图书｜历史")
        after = copy.deepcopy(before)
        after["collections"][0]["name"] = "图书｜历史"
        self.assertTrue(verify_rename(before, after, prepared)["verified"])
        after["relations"] = []
        self.assertFalse(verify_rename(before, after, prepared)["verified"])
        with self.assertRaises(CompanionError):
            prepare_rename(before, {"uuid": "old", "current_name": "错误名称", "name": "图书｜历史"})


if __name__ == "__main__":
    unittest.main()
