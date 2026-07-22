import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "context_diet.py"


class ContextDietTests(unittest.TestCase):
    def run_cli(self, *args, cwd=None, expected=0):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            cwd=cwd,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, expected, result.stderr or result.stdout)
        return result

    def promote_plan(self, plan, target):
        data = json.loads(plan.read_text(encoding="utf-8"))
        original = target.read_text(encoding="utf-8")
        artifacts = {
            "safe": original,
            "recommended": original[:-2],
            "aggressive": original[:-4],
        }
        tiers = {}
        for name, artifact in artifacts.items():
            saved = len(original) - len(artifact)
            tiers[name] = {
                "strategy": "condense",
                "reductionPct": saved / len(original) * 100,
                "savedChars": saved,
                "finalChars": len(artifact),
                "actionIds": ["condense-rule"],
                "protectedLoss": [],
                "inlineRetention": 100,
                "corpusRetention": 100,
                "artifact": artifact,
                "artifactSha256": hashlib.sha256(artifact.encode("utf-8")).hexdigest(),
                "linkedFiles": [],
            }
        data.update({
            "status": "proposed",
            "recommendation": "recommended",
            "protectedFloorChars": len(original) - 4,
            "inventory": [{"id": "rule", "kind": "directive", "text": "Keep this", "protected": False}],
            "actions": [{"id": "condense-rule", "itemId": "rule", "action": "condense",
                         "reason": "remove repetition", "confidence": 0.9, "estimatedSavings": 4}],
            "tiers": tiers,
        })
        plan.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def test_measurement_accounts_for_every_character(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CLAUDE.md"
            target.write_text("# Context\n\nIntro.\n\n## Rules\n\n- Keep this.\n", encoding="utf-8")
            result = self.run_cli(target, "--json")
            data = json.loads(result.stdout)
            self.assertEqual(data["totalChars"], sum(section["chars"] for section in data["sections"]))
            self.assertFalse(data["overLimit"])

            template = json.loads(self.run_cli(target, "--proposal-template").stdout)
            self.assertEqual(set(template["tiers"]), {"safe", "recommended", "aggressive"})
            self.assertEqual(template["tiers"]["safe"]["finalChars"], data["totalChars"])

    def test_plan_lifecycle_and_stale_source_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "AGENTS.md"
            target.write_text("# Rules\n\nKeep this.\n", encoding="utf-8")
            created = json.loads(self.run_cli(target, "--init-plan", "--goal", "Reduce 80% if safe").stdout)
            plan = Path(created["plan"])
            self.assertTrue(plan.is_file())
            self.promote_plan(plan, target)
            self.assertTrue(json.loads(self.run_cli(target, "--check-plan").stdout)["fresh"])

            checkpoint = json.loads(self.run_cli(target, "--checkpoint", "--tier", "recommended").stdout)
            self.assertTrue(Path(checkpoint["path"]).is_file())
            target.write_text("# Rules\n\nKeep this exactly.\n", encoding="utf-8")
            stale = json.loads(self.run_cli(target, "--check-plan", expected=1).stdout)
            self.assertFalse(stale["fresh"])
            self.assertIn("source hash changed", stale["errors"][0])

    def test_complete_reports_reduction_from_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CLAUDE.md"
            target.write_text("# Rules\n\nKeep this sentence and remove repeated prose.\n", encoding="utf-8")
            created = json.loads(self.run_cli(target, "--init-plan").stdout)
            self.promote_plan(Path(created["plan"]), target)
            self.run_cli(target, "--checkpoint", "--tier", "recommended")
            plan = json.loads(Path(created["plan"]).read_text(encoding="utf-8"))
            target.write_text(plan["tiers"]["recommended"]["artifact"], encoding="utf-8")
            result = json.loads(self.run_cli(target, "--complete").stdout)
            self.assertGreater(result["reduction"], 0)
            self.assertGreater(result["reductionPct"], 0)

    def test_rejects_aggressive_tier_below_protected_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CLAUDE.md"
            target.write_text("# Rules\n\nKeep protected context intact.\n", encoding="utf-8")
            created = json.loads(self.run_cli(target, "--init-plan").stdout)
            plan = Path(created["plan"])
            self.promote_plan(plan, target)
            data = json.loads(plan.read_text(encoding="utf-8"))
            data["protectedFloorChars"] = data["original"]["chars"] - 3
            plan.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            checked = json.loads(self.run_cli(target, "--check-plan", expected=1).stdout)
            self.assertIn("aggressive tier falls below protected floor", checked["errors"])

    def test_rejects_changed_goal_without_replan(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "AGENTS.md"
            target.write_text("# Rules\n", encoding="utf-8")
            self.run_cli(target, "--init-plan", "--goal", "safe")
            result = self.run_cli(target, "--init-plan", "--goal", "aggressive", expected=2)
            self.assertIn("different goal", result.stderr)

    def test_imports_a_complete_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CLAUDE.md"
            target.write_text("# Rules\n\nKeep this concise rule.\n", encoding="utf-8")
            created = json.loads(self.run_cli(target, "--init-plan").stdout)
            plan = Path(created["plan"])
            self.promote_plan(plan, target)
            populated = json.loads(plan.read_text(encoding="utf-8"))
            proposal = Path(directory) / "proposal.json"
            proposal.write_text(json.dumps({key: populated[key] for key in (
                "inventory", "actions", "tiers", "recommendation", "protectedFloorChars"
            )}), encoding="utf-8")
            self.run_cli(target, "--init-plan", "--replan")
            imported = json.loads(self.run_cli(target, "--import-proposal", proposal).stdout)
            self.assertTrue(imported["imported"])
            self.assertTrue(json.loads(self.run_cli(target, "--check-plan").stdout)["fresh"])

    def test_complete_verifies_linked_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "CLAUDE.md"
            target.write_text("# Rules\n\nKeep this and route details.\n", encoding="utf-8")
            created = json.loads(self.run_cli(target, "--init-plan").stdout)
            planPath = Path(created["plan"])
            self.promote_plan(planPath, target)
            plan = json.loads(planPath.read_text(encoding="utf-8"))
            linkedContent = "# Details\n\nExternalized detail.\n"
            plan["tiers"]["recommended"]["linkedFiles"] = [{
                "path": "docs/agents/details.md", "content": linkedContent,
                "sha256": hashlib.sha256(linkedContent.encode("utf-8")).hexdigest(),
            }]
            planPath.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            self.run_cli(target, "--checkpoint", "--tier", "recommended")
            target.write_text(plan["tiers"]["recommended"]["artifact"], encoding="utf-8")
            missing = self.run_cli(target, "--complete", expected=2)
            self.assertIn("linked file does not match", missing.stderr)
            linkedPath = Path(directory) / "docs/agents/details.md"
            linkedPath.parent.mkdir(parents=True)
            linkedPath.write_text(linkedContent, encoding="utf-8")
            completed = json.loads(self.run_cli(target, "--complete").stdout)
            self.assertGreater(completed["reduction"], 0)


if __name__ == "__main__":
    unittest.main()
