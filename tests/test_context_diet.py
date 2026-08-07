import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import context_diet


ROOT = Path(__file__).resolve().parents[1]


class AnalyzerCompatibilityTests(unittest.TestCase):
    def test_measurement_accounts_for_every_character(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as temp:
            target = Path(temp) / "AGENTS.md"
            text = "preamble\n## One\na\n## Two\nb\n"
            target.write_text(text, encoding="utf-8")
            measured = context_diet.measure(target, 20)
            self.assertEqual(measured["totalChars"], len(text))
            self.assertEqual(sum(section["chars"] for section in measured["sections"]), len(text))
            self.assertEqual(measured["overBy"], len(text) - 20)

    def test_legacy_json_cli_is_unchanged(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "context_diet.py"), str(ROOT / "SKILL.md"), "--json"],
            check=True,
            text=True,
            capture_output=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["file"], str(ROOT / "SKILL.md"))
        self.assertIn("sections", payload)
        self.assertNotIn("status", payload)

    def test_ablate_dispatch(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "context_diet.py"),
                "ablate",
                "detect",
                str(ROOT / "SKILL.md"),
                "--request",
                "delete the whole context and rebuild from scratch",
                "--json",
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["guidedAblation"])
        self.assertIn("whole_file_removal", payload["reasons"])

    def test_missing_file_still_returns_two(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "context_diet.py"), str(ROOT / "missing.md")],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
