from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kindle_companion.models import CompanionError
from kindle_companion.plan import build_delete_plan, build_put_plan


class PlanTests(unittest.TestCase):
    def test_put_plan_is_deterministic_and_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "book.koplugin" / "source").mkdir(parents=True)
            (root / "book.koplugin" / "_meta.lua").write_text("meta", encoding="utf-8")
            (root / "book.koplugin" / "source" / "main.lua").write_text("main", encoding="utf-8")
            commands = build_put_plan(root, "/koreader/plugins")
        self.assertEqual(commands[0], "mkpath /koreader/plugins")
        self.assertIn("put ", commands[-2])
        self.assertEqual(commands[-1], "exit")

    def test_delete_plan_refuses_broad_targets(self) -> None:
        with self.assertRaises(CompanionError):
            build_delete_plan(["/documents"])

    def test_delete_plan_keeps_exact_paths(self) -> None:
        self.assertEqual(
            build_delete_plan(["/documents/Véra.azw3"]),
            ("cd /", "rm /documents/Véra.azw3", "exit"),
        )
