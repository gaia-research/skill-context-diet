import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context_diet_ablation as ab


ROOT = Path(__file__).resolve().parents[1]
SOURCE = b"""# Agent Context\n\nOptional background explanation that can be removed.\n\n## Safety\n\nNever disclose credentials or bypass authorization.\n\n## Working notes\n\nA historical anecdote with no directive.\n\nKeep output concise for the user.\n"""
MODELS = ["provider/model-a", "provider/model-b"]
DESIGNER = "provider/designer-model"


class AblationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=str(ROOT))
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.target = self.base / "AGENTS.md"
        self.target.write_bytes(SOURCE)
        self.old_state = os.environ.get("CONTEXT_DIET_STATE_DIR")
        os.environ["CONTEXT_DIET_STATE_DIR"] = str(self.base / "state")
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self.old_state is None:
            os.environ.pop("CONTEXT_DIET_STATE_DIR", None)
        else:
            os.environ["CONTEXT_DIET_STATE_DIR"] = self.old_state

    def init(self):
        return ab.init_session(self.target, MODELS, DESIGNER, 2, ["whole_file_removal"])

    def state(self):
        return json.loads((ab.session_dir(self.target.resolve()) / "state.json").read_text(encoding="utf-8"))

    def inventory(self):
        root = ab.session_dir(self.target.resolve())
        return json.loads((root / "inventory.json").read_text(encoding="utf-8"))

    def onboard(self):
        summary = self.init()
        inventory = self.inventory()
        removable = [unit["id"] for unit in inventory["units"] if not unit["protected"]]
        manifest = {
            "approved": True,
            "providerDisclosureAccepted": True,
            "sourceSha256": summary["currentSha256"],
            "designerModel": DESIGNER,
            "protectedUnits": [],
            "cases": [{
                "id": "case-1",
                "prompt": "Summarize the expected behavior.",
                "rubric": "Preserves authorization and concise user-facing behavior.",
                "critical": True,
                "unitIds": removable,
            }],
        }
        path = self.base / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        ab.approve_onboarding(self.target, path)
        return removable

    def evidence(self, kind, model, status="pass", trial=None):
        state = self.state()
        active = state["trials"].get(state.get("activeTrial"))
        raw = {
            "kind": kind,
            "modelId": model,
            "actualModelId": model,
            "judgeModelId": DESIGNER,
            "suiteSha256": state["suiteSha256"],
            "parentSha256": active["parentSha256"] if kind == "trial" else state["revisions"][-1]["sha256"],
            "candidateSha256": active["candidateSha256"] if kind == "trial" else None,
            "trialId": active["id"] if kind == "trial" else None,
            "repetitions": 2,
            "freshContext": True,
            "cases": [{"caseId": "case-1", "runs": [status, status]}],
        }
        if kind == "trial":
            raw["cases"][0]["parentRuns"] = ["pass", "pass"]
        path = self.base / ("%s-%s-%s.json" % (kind, model.replace("/", "-"), status))
        path.write_text(json.dumps(raw), encoding="utf-8")
        return path

    def baseline(self, status_by_model=None):
        status_by_model = status_by_model or {}
        for model in MODELS:
            ab.record_evidence(self.target, self.evidence("baseline", model, status_by_model.get(model, "pass")))

    def ready_trial(self):
        removable = self.onboard()
        self.baseline()
        summary = ab.stage_trial(self.target, removable[0])
        trial_id = summary["activeTrial"]
        for model in MODELS:
            ab.record_evidence(self.target, self.evidence("trial", model))
        return trial_id, summary["candidateSha256"]

    def test_init_creates_private_exact_backup_before_onboarding_and_resumes(self):
        summary = self.init()
        state = self.state()
        root = Path(summary["stateDirectory"])
        snapshot = root / state["revisions"][0]["snapshot"]["path"]
        self.assertEqual(snapshot.read_bytes(), SOURCE)
        self.assertEqual(summary["status"], "onboarding")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o600)
        resumed = self.init()
        self.assertEqual(resumed["sessionId"], summary["sessionId"])
        self.assertEqual(resumed["revisionCount"], 1)

    def test_risk_detection_covers_intent_thresholds_and_protected_loss(self):
        intent = ab.risk_assessment("remove the entire context and start over from scratch", SOURCE)
        self.assertTrue(intent["guidedAblation"])
        self.assertIn("whole_file_removal", intent["reasons"])
        candidate = b"# Agent Context\n"
        assessed = ab.risk_assessment("", SOURCE, candidate)
        self.assertIn("candidate_removes_at_least_20_percent", assessed["reasons"])
        self.assertIn("candidate_removes_multiple_units", assessed["reasons"])
        self.assertIn("candidate_removes_protected_context", assessed["reasons"])

    def test_onboarding_and_every_model_baseline_gate_staging(self):
        removable = self.onboard()
        ab.record_evidence(self.target, self.evidence("baseline", MODELS[0]))
        with self.assertRaises(ab.AblationError):
            ab.stage_trial(self.target, removable[0])
        ab.record_evidence(self.target, self.evidence("baseline", MODELS[1]))
        before = self.target.read_bytes()
        staged = ab.stage_trial(self.target, removable[0])
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(staged["status"], "staged")
        self.assertNotEqual(staged["candidateSha256"], staged["currentSha256"])

    def test_failed_baseline_can_be_replaced_but_never_silently_passes(self):
        removable = self.onboard()
        self.baseline({MODELS[0]: "fail"})
        self.assertEqual(ab.status(self.target)["status"], "baselining")
        with self.assertRaises(ab.AblationError):
            ab.stage_trial(self.target, removable[0])
        ab.record_evidence(self.target, self.evidence("baseline", MODELS[0], "pass"))
        self.assertEqual(ab.status(self.target)["status"], "ready")

    def test_protected_and_empty_file_removals_are_blocked(self):
        self.onboard()
        self.baseline()
        protected = next(unit["id"] for unit in self.inventory()["units"] if unit["protected"])
        with self.assertRaises(ab.AblationError):
            ab.stage_trial(self.target, protected)
        other = self.base / "tiny.md"
        other.write_text("Disposable background prose.\n", encoding="utf-8")
        os.environ["CONTEXT_DIET_STATE_DIR"] = str(self.base / "tiny-state")
        init = ab.init_session(other, [MODELS[0]], DESIGNER, 1)
        inventory = json.loads(Path(init["inventoryPath"]).read_text(encoding="utf-8"))
        unit = inventory["units"][0]
        self.assertFalse(unit["protected"])
        manifest = {
            "approved": True,
            "providerDisclosureAccepted": True,
            "sourceSha256": init["currentSha256"],
            "designerModel": DESIGNER,
            "protectedUnits": [],
            "cases": [{"id": "tiny", "prompt": "Respond.", "rubric": "Responds.", "unitIds": [unit["id"]]}],
        }
        manifest_path = self.base / "tiny-manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        approved = ab.approve_onboarding(other, manifest_path)
        evidence = {
            "kind": "baseline",
            "modelId": MODELS[0],
            "actualModelId": MODELS[0],
            "judgeModelId": DESIGNER,
            "suiteSha256": approved["suiteSha256"],
            "parentSha256": init["currentSha256"],
            "candidateSha256": None,
            "repetitions": 1,
            "freshContext": True,
            "cases": [{"caseId": "tiny", "runs": ["pass"]}],
        }
        evidence_path = self.base / "tiny-evidence.json"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        ab.record_evidence(other, evidence_path)
        with self.assertRaises(ab.AblationError):
            ab.stage_trial(other, unit["id"])

    def test_inconclusive_or_regressed_model_blocks_acceptance(self):
        removable = self.onboard()
        self.baseline()
        staged = ab.stage_trial(self.target, removable[0])
        ab.record_evidence(self.target, self.evidence("trial", MODELS[0], "pass"))
        ab.record_evidence(self.target, self.evidence("trial", MODELS[1], "inconclusive"))
        with self.assertRaises(ab.AblationError):
            ab.accept_trial(self.target, staged["activeTrial"], staged["candidateSha256"])
        self.assertEqual(self.target.read_bytes(), SOURCE)

    def test_accept_requires_trial_and_hash_then_rollback_and_redo_are_exact(self):
        os.chmod(self.target, 0o640)
        trial_id, candidate_sha = self.ready_trial()
        with self.assertRaises(ab.AblationError):
            ab.accept_trial(self.target, trial_id, "0" * 64)
        accepted = ab.accept_trial(self.target, trial_id, candidate_sha)
        candidate = self.target.read_bytes()
        self.assertEqual(ab.sha256_bytes(candidate), candidate_sha)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o640)
        self.assertEqual(accepted["status"], "ready")
        rolled = ab.rollback(self.target, "R0000")
        self.assertEqual(self.target.read_bytes(), SOURCE)
        self.assertEqual(rolled["status"], "ready")
        ab.rollback(self.target)
        self.assertEqual(self.target.read_bytes(), candidate)

    def test_external_drift_and_artifact_tampering_fail_closed(self):
        removable = self.onboard()
        self.baseline()
        self.target.write_bytes(SOURCE + b"external\n")
        with self.assertRaises(ab.AblationError):
            ab.stage_trial(self.target, removable[0])
        self.target.write_bytes(SOURCE)
        staged = ab.stage_trial(self.target, removable[0])
        root = ab.session_dir(self.target.resolve())
        trial = self.state()["trials"][staged["activeTrial"]]
        (root / trial["candidate"]["path"]).write_bytes(b"tampered")
        with self.assertRaises(ab.AblationError):
            ab.status(self.target)

    def test_apply_failure_restores_preapply_bytes(self):
        trial_id, candidate_sha = self.ready_trial()
        original_replace = ab._atomic_replace_target
        calls = {"count": 0}

        def fail_once(target, data, mode):
            calls["count"] += 1
            original_replace(target, data, mode)
            if calls["count"] == 1:
                raise OSError("injected crash")

        with mock.patch.object(ab, "_atomic_replace_target", side_effect=fail_once):
            with self.assertRaises(OSError):
                ab.accept_trial(self.target, trial_id, candidate_sha)
        self.assertEqual(self.target.read_bytes(), SOURCE)
        self.assertEqual(ab.status(self.target)["status"], "review_pending")

    def test_interrupted_prepared_apply_is_not_replayed_automatically(self):
        trial_id, candidate_sha = self.ready_trial()
        root = ab.session_dir(self.target.resolve())
        state = self.state()
        trial = state["trials"][trial_id]
        pre = ab._put_artifact(root, "transactions/X9999-pre.bin", SOURCE)
        state["transaction"] = {
            "id": "X9999",
            "type": "apply",
            "status": "prepared",
            "trial": trial_id,
            "parentSha256": trial["parentSha256"],
            "candidateSha256": candidate_sha,
            "preSnapshot": pre,
            "mode": 0o644,
            "preparedAt": ab.utc_now(),
        }
        state["status"] = "applying"
        ab._save_state(root, state)
        resumed = ab.status(self.target)
        self.assertEqual(resumed["status"], "review_pending")
        self.assertEqual(self.target.read_bytes(), SOURCE)

    def test_unknown_schema_and_symlink_target_fail_closed(self):
        self.init()
        root = ab.session_dir(self.target.resolve())
        state = self.state()
        state["schemaVersion"] = 999
        ab.atomic_json(root / "state.json", state)
        with self.assertRaises(ab.AblationError):
            ab.status(self.target)
        link = self.base / "linked.md"
        try:
            link.symlink_to(self.target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(ab.AblationError):
            ab.init_session(link, [MODELS[0]], DESIGNER, 1)

    def test_lock_contention_is_rejected(self):
        summary = self.init()
        root = Path(summary["stateDirectory"])
        with ab.SessionLock(root):
            with self.assertRaises(ab.AblationError):
                with ab.SessionLock(root):
                    pass

    def test_workflow_and_installer_contracts(self):
        workflow = (ROOT / "ablation.workflow.js").read_text(encoding="utf-8")
        self.assertIn("model: work.model", workflow)
        self.assertIn("missing_subject_coverage", workflow)
        self.assertIn("intendedWorkIds", workflow)
        self.assertIn("label: `judge:", workflow)
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        for required in ("context_diet_ablation.py", "ABLATION.md", "bakeoff.workflow.js", "ablation.workflow.js"):
            self.assertIn(required, installer)


if __name__ == "__main__":
    unittest.main()
