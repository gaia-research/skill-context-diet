#!/usr/bin/env python3
"""Reversible, evidence-gated context ablation for Context Diet.

The module deliberately does not call model providers or execute evaluation
prompts. It owns the safety boundary: snapshots, state, exact-span candidates,
evidence validation, atomic application, recovery, and rollback. A host agent or
``ablation.workflow.js`` may produce the reviewed onboarding/evidence JSON.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import os
import re
import stat
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = 1
WORKFLOW_VERSION = 1
ALIASES = {"opus", "sol", "sonnet", "haiku", "gemini", "gpt"}
RUN_STATUSES = {"pass", "fail", "inconclusive"}
AGGRESSIVE_PATTERNS = (
    ("whole_file_removal", re.compile(r"\b(delete|remove|erase|empty|truncate|disable)\b.{0,50}\b(entire|whole|all|file|context|claude\.md|agents\.md|rules?)\b", re.I | re.S)),
    ("rebuild_from_scratch", re.compile(r"\b(rebuild|rewrite|replace|start over)\b.{0,50}\b(from scratch|entire|whole|completely|new)\b", re.I | re.S)),
    ("intentional_rule_loss", re.compile(r"\b(delete|remove|drop|retire|disable)\b.{0,50}\b(rule|directive|guardrail|section|instruction)s?\b", re.I | re.S)),
)
PROTECTED_PATTERNS = (
    ("authorization/safety", re.compile(r"\b(authori[sz]|safety|permission|approval|forbid|never|do not|must not)\b", re.I)),
    ("CI/incident", re.compile(r"\b(CI|incident|outage|regression|security|secret|credential)\b", re.I)),
    ("exact literal", re.compile(r"\b(exact|literal|verbatim|allowlist|denylist|command|path)\b", re.I)),
    ("bootstrap/routing", re.compile(r"\b(bootstrap|routing|model|provider|load order|context path)\b", re.I)),
    ("user preference", re.compile(r"\b(user preference|user requested|always)\b", re.I)),
)


class AblationError(RuntimeError):
    """A fail-closed user-facing ablation error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(data: Any) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".context-diet-", dir=str(path.parent))
    tmp = Path(name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp), str(path))
        try:
            os.chmod(path, mode)
        except OSError:
            pass
        _fsync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_json(path: Path, data: Any) -> None:
    atomic_write(path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AblationError("cannot read valid JSON from %s: %s" % (path, exc))
    if not isinstance(value, dict):
        raise AblationError("expected a JSON object in %s" % path)
    return value


def state_root() -> Path:
    explicit = os.environ.get("CONTEXT_DIET_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "context-diet"
    return Path.home() / ".local" / "state" / "context-diet"


def canonical_target(path: Path, must_exist: bool = True) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise AblationError("symlink targets are not supported: %s" % expanded)
    try:
        resolved = expanded.resolve(strict=must_exist)
    except OSError as exc:
        raise AblationError("cannot resolve target %s: %s" % (expanded, exc))
    if must_exist and not resolved.is_file():
        raise AblationError("target is not a regular file: %s" % resolved)
    return resolved


def target_id(target: Path) -> str:
    return hashlib.sha256(str(target).encode("utf-8")).hexdigest()[:20]


def session_dir(target: Path) -> Path:
    return state_root() / "ablation" / target_id(target)


def _validate_model_id(model_id: Any) -> str:
    if not isinstance(model_id, str) or not model_id.strip():
        raise AblationError("model identifiers must be non-empty strings")
    value = model_id.strip()
    if value.lower() in ALIASES or "/" not in value or any(ch.isspace() for ch in value):
        raise AblationError("use an exact configured provider/model identifier, not alias %r" % value)
    return value


def parse_models(values: Iterable[str]) -> List[str]:
    models: List[str] = []
    for value in values:
        for item in value.split(","):
            item = item.strip()
            if item:
                model = _validate_model_id(item)
                if model not in models:
                    models.append(model)
    if not models:
        raise AblationError("at least one exact model identifier is required")
    return models


def _parse_model_routes(values: Iterable[str]) -> List[Dict[str, str]]:
    routes: List[Dict[str, str]] = []
    for value in values:
        if "=" not in value:
            raise AblationError("model routes must use exact-provider/model=tier")
        model, tier = value.rsplit("=", 1)
        routes.append({"modelId": _validate_model_id(model), "tier": tier.strip().lower()})
    return routes


def risk_assessment(request: str, original: bytes, candidate: Optional[bytes] = None) -> Dict[str, Any]:
    reasons: List[str] = []
    for name, pattern in AGGRESSIVE_PATTERNS:
        if pattern.search(request or ""):
            reasons.append(name)
    removed_ratio = 0.0
    removed_units = 0
    protected_removed: List[str] = []
    if candidate is not None:
        removed_ratio = max(0.0, (len(original) - len(candidate)) / max(1, len(original)))
        if removed_ratio >= 0.20:
            reasons.append("candidate_removes_at_least_20_percent")
        original_inventory = build_inventory(original)
        for unit in original_inventory["units"]:
            span = original[unit["byteStart"]:unit["byteEnd"]]
            if span and span not in candidate:
                removed_units += 1
                if unit["protected"]:
                    protected_removed.append(unit["id"])
        if removed_units >= 2:
            reasons.append("candidate_removes_multiple_units")
        if protected_removed:
            reasons.append("candidate_removes_protected_context")
        if not candidate.strip():
            reasons.append("candidate_empties_file")
    reasons = list(dict.fromkeys(reasons))
    return {
        "guidedAblation": bool(reasons),
        "reasons": reasons,
        "removedCharacterRatio": round(removed_ratio, 4),
        "removedUnits": removed_units,
        "protectedUnitsRemoved": protected_removed,
        "thresholdVersion": 1,
    }


def preflight(request: str, original: bytes, candidate: Optional[bytes],
              model_routes: Iterable[str]) -> Dict[str, Any]:
    """Return an invocation-scoped suggestion; never starts or edits a session."""
    assessment = risk_assessment(request, original, candidate)
    routes = _parse_model_routes(model_routes)
    high_tiers = {"big", "high", "frontier", "premium"}
    capable = [route for route in routes if route["tier"] in high_tiers]
    suggestion_reasons = list(assessment["reasons"])
    if capable:
        suggestion_reasons.append("user_invocation_has_declared_high_tier_model")
    return {
        "invocationScoped": True,
        "suggestAblation": assessment["guidedAblation"] or bool(capable),
        "suggestionOnly": True,
        "reasons": suggestion_reasons,
        "availableHighTierModels": capable,
        "riskAssessment": assessment,
        "message": (
            "Offer guided ablation; do not start it without explicit user confirmation."
            if assessment["guidedAblation"] or capable else
            "No ablation suggestion from this pre-flight."
        ),
    }


def _line_kind(raw: bytes) -> str:
    stripped = raw.lstrip()
    if stripped.startswith(b"#"):
        return "heading"
    if stripped.startswith((b"```", b"~~~")):
        return "code"
    if re.match(br"(?:[-+*]|\d+[.)])\s", stripped):
        return "list"
    return "paragraph"


def build_inventory(source: bytes) -> Dict[str, Any]:
    try:
        source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AblationError("ablation requires UTF-8 context: %s" % exc)
    lines = source.splitlines(keepends=True)
    blocks: List[Tuple[int, int, bytes]] = []
    offset = 0
    start: Optional[int] = None
    buf: List[bytes] = []
    in_fence: Optional[bytes] = None

    def flush(end: int) -> None:
        nonlocal start, buf
        if start is not None and b"".join(buf).strip():
            blocks.append((start, end, b"".join(buf)))
        start = None
        buf = []

    for line in lines:
        stripped = line.lstrip()
        line_start = offset
        offset += len(line)
        fence = stripped[:3] if stripped.startswith((b"```", b"~~~")) else None
        if in_fence:
            if start is None:
                start = line_start
            buf.append(line)
            if fence == in_fence:
                in_fence = None
            continue
        if fence:
            if start is not None:
                flush(line_start)
            start = line_start
            buf = [line]
            in_fence = fence
            continue
        if stripped.startswith(b"#"):
            if start is not None:
                flush(line_start)
            blocks.append((line_start, offset, line))
            continue
        if not line.strip():
            if start is not None:
                buf.append(line)
                flush(offset)
            continue
        if start is None:
            start = line_start
        buf.append(line)
    flush(len(source))

    units: List[Dict[str, Any]] = []
    for index, (begin, end, content) in enumerate(blocks, 1):
        kind = _line_kind(content)
        decoded = content.decode("utf-8")
        reasons: List[str] = []
        if kind == "heading":
            reasons.append("structural heading")
        for label, pattern in PROTECTED_PATTERNS:
            if pattern.search(decoded):
                reasons.append(label)
        first = next((line.strip() for line in decoded.splitlines() if line.strip()), "")
        units.append({
            "id": "CD-%04d" % index,
            "kind": kind,
            "label": first[:120],
            "byteStart": begin,
            "byteEnd": end,
            "chars": len(decoded),
            "sha256": sha256_bytes(content),
            "protected": bool(reasons),
            "protectedReasons": list(dict.fromkeys(reasons)),
        })
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sourceSha256": sha256_bytes(source),
        "generatedAt": utc_now(),
        "units": units,
    }


class SessionLock:
    def __init__(self, root: Path):
        self.path = root / ".lock"
        self.acquired = False

    def __enter__(self) -> "SessionLock":
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for attempt in range(2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w", encoding="ascii") as handle:
                    handle.write(str(os.getpid()))
                    handle.flush()
                    os.fsync(handle.fileno())
                self.acquired = True
                return self
            except FileExistsError:
                if attempt or not self._remove_if_stale():
                    raise AblationError("another ablation command holds %s" % self.path)
        raise AblationError("could not acquire session lock")

    def _remove_if_stale(self) -> bool:
        try:
            pid = int(self.path.read_text(encoding="ascii").strip())
            os.kill(pid, 0)
            return False
        except ProcessLookupError:
            try:
                self.path.unlink()
                return True
            except OSError:
                return False
        except (OSError, ValueError):
            return False

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def _safe_artifact(root: Path, ref: Dict[str, Any]) -> Path:
    relative = ref.get("path")
    expected = ref.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected, str):
        raise AblationError("invalid artifact reference")
    candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise AblationError("unsafe or missing artifact %r: %s" % (relative, exc))
    if candidate.is_symlink() or not resolved.is_file():
        raise AblationError("artifact must be a regular non-symlink file: %s" % relative)
    actual = sha256_bytes(resolved.read_bytes())
    if actual != expected:
        raise AblationError("artifact integrity failure for %s" % relative)
    return resolved


def _put_artifact(root: Path, relative: str, data: bytes) -> Dict[str, str]:
    path = root / relative
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise AblationError("artifact path escapes session root: %s" % relative)
    digest = sha256_bytes(data)
    if path.exists():
        if path.is_symlink() or sha256_bytes(path.read_bytes()) != digest:
            raise AblationError("refusing to overwrite mismatched artifact %s" % relative)
    else:
        atomic_write(path, data)
    return {"path": relative, "sha256": digest}


def _snapshot(root: Path, data: bytes) -> Dict[str, str]:
    digest = sha256_bytes(data)
    return _put_artifact(root, "snapshots/%s.bin" % digest, data)


def _event(root: Path, event: str, **details: Any) -> None:
    record = {"at": utc_now(), "event": event}
    record.update(details)
    path = root / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    fd = os.open(str(path), flags, 0o600)
    with os.fdopen(fd, "ab") as handle:
        handle.write(canonical_json(record))
        handle.flush()
        os.fsync(handle.fileno())


def _save_state(root: Path, state: Dict[str, Any]) -> None:
    state["updatedAt"] = utc_now()
    atomic_json(root / "state.json", state)


def _stored_evidence_verdict(evidence: Dict[str, Any]) -> str:
    kind = evidence.get("kind")
    cases = evidence.get("cases")
    repetitions = evidence.get("repetitions")
    if kind not in {"baseline", "trial"} or not isinstance(cases, list) or not isinstance(repetitions, int):
        raise AblationError("stored evidence has an invalid shape")
    verdict = "no_regression_observed"
    for result in cases:
        if not isinstance(result, dict):
            raise AblationError("stored evidence case has an invalid shape")
        runs = result.get("runs")
        if not isinstance(runs, list) or len(runs) != repetitions or any(value not in RUN_STATUSES for value in runs):
            raise AblationError("stored evidence has invalid candidate runs")
        parent_runs = result.get("parentRuns", [])
        if kind == "trial" and (not isinstance(parent_runs, list) or len(parent_runs) != repetitions or any(value not in RUN_STATUSES for value in parent_runs)):
            raise AblationError("stored trial evidence has invalid parent runs")
        if "inconclusive" in runs or "inconclusive" in parent_runs:
            return "inconclusive"
        if "fail" in runs:
            return "baseline_failed" if kind == "baseline" else "regression_observed"
        if kind == "trial" and "fail" in parent_runs:
            return "inconclusive"
    return verdict


def _validate_evidence_summary(root: Path, model: str, summary: Dict[str, Any],
                               suite_sha: Optional[str]) -> None:
    evidence = _read_json(_safe_artifact(root, summary["artifact"]))
    if evidence.get("modelId") != model or evidence.get("actualModelId") != model:
        raise AblationError("stored evidence model identity mismatch for %s" % model)
    if evidence.get("suiteSha256") != suite_sha:
        raise AblationError("stored evidence suite mismatch for %s" % model)
    if _stored_evidence_verdict(evidence) != summary.get("verdict"):
        raise AblationError("stored evidence verdict mismatch for %s" % model)
    evidence_head = evidence.get("candidateSha256") if evidence.get("kind") == "trial" else evidence.get("parentSha256")
    if evidence_head != summary.get("headSha256"):
        raise AblationError("stored evidence checkpoint mismatch for %s" % model)


def _trial_unit_ids(trial: Dict[str, Any]) -> List[str]:
    values = trial.get("unitIds")
    if values is None and trial.get("unitId"):
        values = [trial["unitId"]]
    if not isinstance(values, list) or not values or any(not isinstance(item, str) for item in values):
        raise AblationError("trial has no valid unit IDs")
    if len(values) != len(set(values)):
        raise AblationError("trial repeats an inventory unit")
    return values


def _bytes_without_units(original: bytes, units: Dict[str, Dict[str, Any]],
                         removed_ids: Iterable[str]) -> bytes:
    spans = []
    for unit_id in removed_ids:
        unit = units.get(unit_id)
        if not unit:
            raise AblationError("unknown removed inventory unit %s" % unit_id)
        spans.append((unit["byteStart"], unit["byteEnd"]))
    spans.sort()
    if any(spans[index][1] > spans[index + 1][0] for index in range(len(spans) - 1)):
        raise AblationError("inventory deletion spans overlap")
    parts = []
    offset = 0
    for begin, end in spans:
        parts.append(original[offset:begin])
        offset = end
    parts.append(original[offset:])
    return b"".join(parts)


def _validate_refs(root: Path, state: Dict[str, Any]) -> None:
    revisions = state.get("revisions", [])
    if not revisions:
        raise AblationError("state has no revisions")
    for revision in revisions:
        snapshot = _safe_artifact(root, revision["snapshot"])
        if sha256_bytes(snapshot.read_bytes()) != revision.get("sha256"):
            raise AblationError("revision snapshot hash mismatch for %s" % revision.get("id"))
    inventory = _read_json(_safe_artifact(root, state["inventory"]))
    if inventory.get("sourceSha256") != revisions[0].get("sha256"):
        raise AblationError("inventory is not bound to the original checkpoint")
    units = {unit.get("id"): unit for unit in inventory.get("units", []) if isinstance(unit, dict)}
    onboarding = None
    if state.get("onboarding"):
        onboarding = _read_json(_safe_artifact(root, state["onboarding"]))
        if onboarding.get("sourceSha256") != revisions[0].get("sha256"):
            raise AblationError("onboarding is not bound to the original checkpoint")
        expected_suite = sha256_bytes(canonical_json(onboarding.get("cases")))
        if expected_suite != state.get("suiteSha256"):
            raise AblationError("onboarding suite hash mismatch")
    for model, baseline in state.get("baselines", {}).items():
        _validate_evidence_summary(root, model, baseline, state.get("suiteSha256"))
    for revision in revisions:
        for model, baseline in revision.get("baselines", {}).items():
            _validate_evidence_summary(root, model, baseline, state.get("suiteSha256"))
    revision_ids = {revision.get("id"): revision for revision in revisions}
    original_bytes = _safe_artifact(root, revisions[0]["snapshot"]).read_bytes()
    for trial in state.get("trials", {}).values():
        candidate = _safe_artifact(root, trial["candidate"])
        _safe_artifact(root, trial["diff"])
        candidate_bytes = candidate.read_bytes()
        if sha256_bytes(candidate_bytes) != trial.get("candidateSha256"):
            raise AblationError("trial candidate hash mismatch for %s" % trial.get("id"))
        parent = revision_ids.get(trial.get("parentRevision"))
        if not parent or parent.get("sha256") != trial.get("parentSha256"):
            raise AblationError("trial parent checkpoint mismatch for %s" % trial.get("id"))
        trial_ids = _trial_unit_ids(trial)
        prior_ids = parent.get("removedUnits", [])
        concurrency = state.get("concurrency", 1)
        selected = [units.get(unit_id) for unit_id in trial_ids]
        if (len(trial_ids) > concurrency or any(unit is None or unit.get("protected") for unit in selected) or
                any(unit_id in prior_ids for unit_id in trial_ids) or
                trial.get("removedUnits") != prior_ids + trial_ids):
            raise AblationError("trial is not a valid bounded inventory deletion")
        if onboarding and any(unit_id in onboarding.get("protectedUnits", []) for unit_id in trial_ids):
            raise AblationError("trial deletes an onboarding-protected unit")
        parent_bytes = _safe_artifact(root, parent["snapshot"]).read_bytes()
        expected_parent = _bytes_without_units(original_bytes, units, prior_ids)
        expected_candidate = _bytes_without_units(original_bytes, units, prior_ids + trial_ids)
        if parent_bytes != expected_parent or candidate_bytes != expected_candidate:
            raise AblationError("trial candidate is not the recorded exact-span deletion")
        for model, evidence in trial.get("evidence", {}).items():
            _validate_evidence_summary(root, model, evidence, state.get("suiteSha256"))
    transaction = state.get("transaction")
    if transaction and transaction.get("preSnapshot"):
        pre = _safe_artifact(root, transaction["preSnapshot"])
        expected = transaction.get("parentSha256") or transaction.get("fromSha256")
        if sha256_bytes(pre.read_bytes()) != expected:
            raise AblationError("transaction pre-snapshot hash mismatch")


def _load_state(root: Path) -> Dict[str, Any]:
    state = _read_json(root / "state.json")
    if state.get("schemaVersion") != SCHEMA_VERSION:
        raise AblationError("unsupported ablation state schema %r" % state.get("schemaVersion"))
    _validate_refs(root, state)
    return state


def _current_revision(state: Dict[str, Any]) -> Dict[str, Any]:
    current = state.get("currentRevision")
    for revision in state.get("revisions", []):
        if revision.get("id") == current:
            return revision
    raise AblationError("current revision is missing")


def _target_bytes(state: Dict[str, Any]) -> bytes:
    target = canonical_target(Path(state["target"]))
    return target.read_bytes()


def _require_live_head(state: Dict[str, Any]) -> bytes:
    live = _target_bytes(state)
    expected = _current_revision(state)["sha256"]
    actual = sha256_bytes(live)
    if actual != expected:
        raise AblationError("target drift: expected %s, found %s" % (expected, actual))
    return live


def _trial(state: Dict[str, Any], trial_id: Optional[str] = None) -> Dict[str, Any]:
    active = state.get("activeTrial")
    wanted = trial_id or active
    if not wanted or wanted not in state.get("trials", {}):
        raise AblationError("no matching active trial")
    if active != wanted:
        raise AblationError("trial %s is not active" % wanted)
    return state["trials"][wanted]


def _atomic_replace_target(target: Path, data: bytes, mode: int) -> None:
    atomic_write(target, data, mode=mode)
    if sha256_bytes(target.read_bytes()) != sha256_bytes(data):
        raise AblationError("post-write target verification failed")


def _write_transaction(root: Path, transaction: Dict[str, Any]) -> None:
    txid = transaction["id"]
    atomic_json(root / "transactions" / (txid + ".json"), transaction)


def _finalize_apply(root: Path, state: Dict[str, Any]) -> None:
    tx = state.get("transaction")
    if not tx or tx.get("type") != "apply":
        raise AblationError("missing apply transaction")
    trial = state["trials"][tx["trial"]]
    revision_id = "R%04d" % state["nextRevision"]
    state["nextRevision"] += 1
    candidate_bytes = _safe_artifact(root, trial["candidate"]).read_bytes()
    snapshot = _snapshot(root, candidate_bytes)
    promoted: Dict[str, Any] = {}
    for model, summary in trial["evidence"].items():
        promoted[model] = copy.deepcopy(summary)
        promoted[model]["headSha256"] = trial["candidateSha256"]
    revision = {
        "id": revision_id,
        "sha256": trial["candidateSha256"],
        "snapshot": snapshot,
        "mode": tx["mode"],
        "createdAt": utc_now(),
        "action": "accepted_ablation",
        "trial": trial["id"],
        "removedUnits": list(trial["removedUnits"]),
        "baselines": copy.deepcopy(promoted),
    }
    state["revisions"].append(revision)
    state["currentRevision"] = revision_id
    state["baselines"] = promoted
    trial["status"] = "accepted"
    trial["decidedAt"] = utc_now()
    state["activeTrial"] = None
    state["status"] = "ready"
    tx["status"] = "committed"
    tx["committedAt"] = utc_now()
    _write_transaction(root, tx)
    state["lastTransaction"] = tx["id"]
    state["transaction"] = None
    _save_state(root, state)
    _event(root, "trial_accepted", trial=trial["id"], revision=revision_id, candidateSha256=trial["candidateSha256"])


def _finalize_rollback(root: Path, state: Dict[str, Any]) -> None:
    tx = state.get("transaction")
    if not tx or tx.get("type") != "rollback":
        raise AblationError("missing rollback transaction")
    target_revision = next((r for r in state["revisions"] if r["id"] == tx["targetRevision"]), None)
    if target_revision is None:
        raise AblationError("rollback target revision disappeared")
    revision_id = "R%04d" % state["nextRevision"]
    state["nextRevision"] += 1
    revision = {
        "id": revision_id,
        "sha256": target_revision["sha256"],
        "snapshot": copy.deepcopy(target_revision["snapshot"]),
        "mode": target_revision["mode"],
        "createdAt": utc_now(),
        "action": "rollback",
        "restoredRevision": target_revision["id"],
        "removedUnits": list(target_revision.get("removedUnits", [])),
        "baselines": copy.deepcopy(target_revision.get("baselines", {})),
    }
    state["revisions"].append(revision)
    state["currentRevision"] = revision_id
    state["baselines"] = copy.deepcopy(revision["baselines"])
    state["status"] = "ready"
    tx["status"] = "committed"
    tx["committedAt"] = utc_now()
    _write_transaction(root, tx)
    state["lastTransaction"] = tx["id"]
    state["transaction"] = None
    _save_state(root, state)
    _event(root, "rollback_committed", revision=revision_id, restoredRevision=target_revision["id"])


def _reconcile(root: Path, state: Dict[str, Any]) -> bool:
    status = state.get("status")
    if status not in {"applying", "rolling_back"}:
        return False
    tx = state.get("transaction")
    if not tx:
        state["status"] = "recovery_required"
        _save_state(root, state)
        return True
    live_sha = sha256_bytes(_target_bytes(state))
    if status == "applying":
        if live_sha == tx["candidateSha256"]:
            _finalize_apply(root, state)
        elif live_sha == tx["parentSha256"]:
            tx["status"] = "not_applied"
            _write_transaction(root, tx)
            state["transaction"] = None
            state["status"] = "review_pending"
            _save_state(root, state)
            _event(root, "apply_recovered_without_replay", trial=tx["trial"])
        else:
            state["status"] = "recovery_required"
            _save_state(root, state)
        return True
    if live_sha == tx["targetSha256"]:
        _finalize_rollback(root, state)
    elif live_sha == tx["fromSha256"]:
        tx["status"] = "not_applied"
        _write_transaction(root, tx)
        state["transaction"] = None
        state["status"] = "ready"
        _save_state(root, state)
        _event(root, "rollback_recovered_without_replay", targetRevision=tx["targetRevision"])
    else:
        state["status"] = "recovery_required"
        _save_state(root, state)
    return True


def _open(path: Path) -> Tuple[Path, Dict[str, Any]]:
    target = canonical_target(path)
    root = session_dir(target)
    if not (root / "state.json").is_file():
        raise AblationError("no ablation session for %s; run init first" % target)
    state = _load_state(root)
    if state.get("target") != str(target):
        raise AblationError("session target identity mismatch")
    _reconcile(root, state)
    state = _load_state(root)
    return root, state


def init_session(path: Path, models: List[str], designer_model: str, repetitions: int,
                 trigger_reasons: Optional[List[str]] = None, concurrency: int = 1) -> Dict[str, Any]:
    target = canonical_target(path)
    models = parse_models(models)
    designer_model = _validate_model_id(designer_model)
    if repetitions < 1 or repetitions > 10:
        raise AblationError("repetitions must be between 1 and 10")
    if concurrency < 1 or concurrency > 10:
        raise AblationError("concurrency must be between 1 and 10")
    root = session_dir(target)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    with SessionLock(root):
        if (root / "state.json").exists():
            state = _load_state(root)
            if (state.get("models") != models or state.get("designerModel") != designer_model or
                    state.get("repetitions") != repetitions or state.get("concurrency", 1) != concurrency):
                raise AblationError(
                    "an immutable session already exists with different model/evaluation settings; "
                    "resume it or select a separate CONTEXT_DIET_STATE_DIR for a new generation"
                )
            return session_summary(root, state)
        source = target.read_bytes()
        if not source.strip():
            raise AblationError("cannot ablate an empty context file")
        mode = stat.S_IMODE(target.stat().st_mode)
        snapshot = _snapshot(root, source)
        inventory = build_inventory(source)
        inventory_ref = _put_artifact(root, "inventory.json", json.dumps(inventory, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        created = utc_now()
        state: Dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "workflowVersion": WORKFLOW_VERSION,
            "sessionId": target_id(target),
            "target": str(target),
            "createdAt": created,
            "updatedAt": created,
            "status": "onboarding",
            "nextAction": "review inventory.json and approve an onboarding manifest",
            "triggerReasons": list(trigger_reasons or []),
            "models": models,
            "designerModel": designer_model,
            "repetitions": repetitions,
            "concurrency": concurrency,
            "inventory": inventory_ref,
            "onboarding": None,
            "suiteSha256": None,
            "baselines": {},
            "revisions": [{
                "id": "R0000",
                "sha256": sha256_bytes(source),
                "snapshot": snapshot,
                "mode": mode,
                "createdAt": created,
                "action": "original",
                "removedUnits": [],
                "baselines": {},
            }],
            "currentRevision": "R0000",
            "trials": {},
            "activeTrial": None,
            "nextTrial": 1,
            "nextRevision": 1,
            "nextTransaction": 1,
            "transaction": None,
            "lastTransaction": None,
        }
        _save_state(root, state)
        _event(root, "session_initialized", originalSha256=sha256_bytes(source), models=models,
               concurrency=concurrency)
        return session_summary(root, state)


def _load_inventory(root: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    return _read_json(_safe_artifact(root, state["inventory"]))


def approve_onboarding(path: Path, manifest_path: Path) -> Dict[str, Any]:
    target = canonical_target(path)
    root = session_dir(target)
    with SessionLock(root):
        root, state = _open(target)
        if state["status"] != "onboarding":
            raise AblationError("onboarding is already complete for this source generation")
        manifest = _read_json(manifest_path)
        if manifest.get("approved") is not True or manifest.get("providerDisclosureAccepted") is not True:
            raise AblationError("manifest must record approved=true and providerDisclosureAccepted=true")
        if manifest.get("sourceSha256") != _current_revision(state)["sha256"]:
            raise AblationError("onboarding source hash does not match the original checkpoint")
        if _validate_model_id(manifest.get("designerModel")) != state["designerModel"]:
            raise AblationError("onboarding designer model does not match configured exact model")
        cases = manifest.get("cases")
        if not isinstance(cases, list) or len(cases) < 3 or len(cases) > 7:
            raise AblationError("onboarding must include 3-7 evaluation cases")
        inventory = _load_inventory(root, state)
        unit_ids = {unit["id"] for unit in inventory["units"]}
        case_ids = set()
        normalized_cases = []
        for case in cases:
            if not isinstance(case, dict):
                raise AblationError("each evaluation case must be an object")
            case_id = case.get("id")
            if not isinstance(case_id, str) or not case_id or case_id in case_ids:
                raise AblationError("evaluation case ids must be unique non-empty strings")
            if not isinstance(case.get("prompt"), str) or not isinstance(case.get("rubric"), str):
                raise AblationError("case %s requires prompt and rubric strings" % case_id)
            mapped = case.get("unitIds", [])
            if not isinstance(mapped, list) or any(unit not in unit_ids for unit in mapped):
                raise AblationError("case %s references an unknown unit" % case_id)
            case_ids.add(case_id)
            normalized_cases.append({
                "id": case_id,
                "prompt": case["prompt"],
                "rubric": case["rubric"],
                "critical": bool(case.get("critical", True)),
                "unitIds": mapped,
            })
        extra_protected = manifest.get("protectedUnits", [])
        if not isinstance(extra_protected, list) or any(unit not in unit_ids for unit in extra_protected):
            raise AblationError("protectedUnits contains an unknown unit")
        sealed = {
            "schemaVersion": SCHEMA_VERSION,
            "approved": True,
            "providerDisclosureAccepted": True,
            "sourceSha256": manifest["sourceSha256"],
            "designerModel": state["designerModel"],
            "protectedUnits": sorted(set(extra_protected)),
            "cases": normalized_cases,
            "approvedAt": utc_now(),
        }
        payload = json.dumps(sealed, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
        onboarding_ref = _put_artifact(root, "onboarding.json", payload)
        state["onboarding"] = onboarding_ref
        state["suiteSha256"] = sha256_bytes(canonical_json(normalized_cases))
        state["status"] = "baselining"
        state["nextAction"] = "record a passing fresh-context baseline for every configured model"
        _save_state(root, state)
        _event(root, "onboarding_approved", onboardingSha256=onboarding_ref["sha256"], suiteSha256=state["suiteSha256"])
        return session_summary(root, state)


def _onboarding(root: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    if not state.get("onboarding"):
        raise AblationError("onboarding has not been approved")
    return _read_json(_safe_artifact(root, state["onboarding"]))


def _validate_runs(value: Any, repetitions: int, label: str) -> List[str]:
    if not isinstance(value, list) or len(value) != repetitions or any(item not in RUN_STATUSES for item in value):
        raise AblationError("%s must contain exactly %d pass/fail/inconclusive runs" % (label, repetitions))
    return list(value)


def _normalize_evidence(root: Path, state: Dict[str, Any], raw: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    kind = raw.get("kind")
    if kind not in {"baseline", "trial"}:
        raise AblationError("evidence kind must be baseline or trial")
    model = _validate_model_id(raw.get("modelId"))
    actual = _validate_model_id(raw.get("actualModelId"))
    judge = _validate_model_id(raw.get("judgeModelId"))
    if model not in state["models"] or actual != model:
        raise AblationError("requested and actual exact model identity must match a configured model")
    if judge != state["designerModel"]:
        raise AblationError("judge identity does not match the configured designer model")
    if raw.get("suiteSha256") != state["suiteSha256"]:
        raise AblationError("evidence suite hash is stale or mismatched")
    if raw.get("freshContext") is not True:
        raise AblationError("evidence must affirm freshContext=true")
    if raw.get("repetitions") != state["repetitions"]:
        raise AblationError("evidence repetition count does not match session configuration")
    parent_sha = raw.get("parentSha256")
    candidate_sha = raw.get("candidateSha256")
    if kind == "baseline":
        if parent_sha != _current_revision(state)["sha256"] or candidate_sha not in (None, parent_sha):
            raise AblationError("baseline evidence is not bound to the current checkpoint")
    else:
        trial = _trial(state, raw.get("trialId"))
        if parent_sha != trial["parentSha256"] or candidate_sha != trial["candidateSha256"]:
            raise AblationError("trial evidence hashes do not match the active candidate")
    suite = _onboarding(root, state)
    expected_cases = {case["id"]: case for case in suite["cases"]}
    supplied = raw.get("cases")
    if not isinstance(supplied, list):
        raise AblationError("evidence cases must be an array")
    normalized_cases = []
    seen = set()
    for result in supplied:
        if not isinstance(result, dict) or result.get("caseId") not in expected_cases:
            raise AblationError("evidence contains an unknown case")
        case_id = result["caseId"]
        if case_id in seen:
            raise AblationError("evidence contains duplicate case %s" % case_id)
        seen.add(case_id)
        runs = _validate_runs(result.get("runs"), state["repetitions"], "%s runs" % case_id)
        normalized = {"caseId": case_id, "runs": runs}
        if kind == "trial":
            normalized["parentRuns"] = _validate_runs(result.get("parentRuns"), state["repetitions"], "%s parentRuns" % case_id)
        normalized_cases.append(normalized)
    if seen != set(expected_cases):
        raise AblationError("evidence must cover every sealed evaluation case")
    normalized = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": kind,
        "modelId": model,
        "actualModelId": actual,
        "judgeModelId": judge,
        "suiteSha256": state["suiteSha256"],
        "parentSha256": parent_sha,
        "candidateSha256": candidate_sha,
        "trialId": raw.get("trialId") if kind == "trial" else None,
        "repetitions": state["repetitions"],
        "freshContext": True,
        "cases": sorted(normalized_cases, key=lambda item: item["caseId"]),
        "recordedAt": utc_now(),
    }
    return normalized, _stored_evidence_verdict(normalized)


def _evidence_objects(path: Path) -> List[Dict[str, Any]]:
    raw = _read_json(path)
    if "evidence" in raw:
        values = raw["evidence"]
        if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
            raise AblationError("evidence bundle must contain an array of objects")
        return values
    return [raw]


def record_evidence(path: Path, evidence_path: Path) -> Dict[str, Any]:
    target = canonical_target(path)
    root = session_dir(target)
    with SessionLock(root):
        root, state = _open(target)
        if state["status"] in {"onboarding", "applying", "rolling_back", "recovery_required"}:
            raise AblationError("state %s cannot accept evidence" % state["status"])
        imported = []
        for raw in _evidence_objects(evidence_path):
            normalized, verdict = _normalize_evidence(root, state, raw)
            model = normalized["modelId"]
            data = json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
            if normalized["kind"] == "baseline":
                evidence_id = sha256_bytes(data)[:12]
                relative = "baselines/%s/%s-%s.json" % (_current_revision(state)["id"], hashlib.sha256(model.encode()).hexdigest()[:16], evidence_id)
                artifact = _put_artifact(root, relative, data)
                state["baselines"][model] = {"artifact": artifact, "verdict": verdict, "headSha256": normalized["parentSha256"]}
                imported.append({"kind": "baseline", "model": model, "verdict": verdict})
                _event(root, "baseline_recorded", model=model, verdict=verdict, evidenceSha256=artifact["sha256"])
            else:
                trial = _trial(state, normalized["trialId"])
                evidence_id = sha256_bytes(data)[:12]
                relative = "trials/%s/evidence-%s-%s.json" % (trial["id"], hashlib.sha256(model.encode()).hexdigest()[:16], evidence_id)
                artifact = _put_artifact(root, relative, data)
                trial["evidence"][model] = {"artifact": artifact, "verdict": verdict, "headSha256": normalized["candidateSha256"]}
                imported.append({"kind": "trial", "model": model, "verdict": verdict})
                _event(root, "trial_evidence_recorded", trial=trial["id"], model=model, verdict=verdict, evidenceSha256=artifact["sha256"])
        if state.get("activeTrial"):
            trial = _trial(state)
            state["status"] = "review_pending" if set(trial["evidence"]) == set(state["models"]) else "testing"
            state["nextAction"] = "accept with trial id and candidate hash, or reject" if state["status"] == "review_pending" else "record missing model evidence"
        else:
            complete = set(state["baselines"]) == set(state["models"])
            passing = complete and all(item["verdict"] == "no_regression_observed" for item in state["baselines"].values())
            state["status"] = "ready" if passing else "baselining"
            state["nextAction"] = "stage one unprotected inventory unit" if passing else "record passing baselines for every configured model"
            _current_revision(state)["baselines"] = copy.deepcopy(state["baselines"])
        _save_state(root, state)
        summary = session_summary(root, state)
        summary["imported"] = imported
        return summary


def _unit_by_id(inventory: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
    for unit in inventory["units"]:
        if unit["id"] == unit_id:
            return unit
    raise AblationError("unknown inventory unit %s" % unit_id)


def stage_trial(path: Path, unit_ids: Any) -> Dict[str, Any]:
    target = canonical_target(path)
    requested = [unit_ids] if isinstance(unit_ids, str) else list(unit_ids)
    if not requested or any(not isinstance(unit_id, str) for unit_id in requested):
        raise AblationError("at least one inventory unit is required")
    if len(requested) != len(set(requested)):
        raise AblationError("a trial cannot repeat an inventory unit")
    root = session_dir(target)
    with SessionLock(root):
        root, state = _open(target)
        concurrency = state.get("concurrency", 1)
        if len(requested) > concurrency:
            raise AblationError("trial requests %d units but session concurrency is %d" % (len(requested), concurrency))
        if state["status"] != "ready" or state.get("activeTrial"):
            raise AblationError("a trial may be staged only from ready with no active trial")
        current_sha = _current_revision(state)["sha256"]
        if (set(state["baselines"]) != set(state["models"]) or
                any(item["verdict"] != "no_regression_observed" or item.get("headSha256") != current_sha
                    for item in state["baselines"].values())):
            raise AblationError("all configured models need passing baselines for the current checkpoint")
        live = _require_live_head(state)
        inventory = _load_inventory(root, state)
        units = {unit["id"]: unit for unit in inventory["units"]}
        selected = [_unit_by_id(inventory, unit_id) for unit_id in requested]
        onboarding = _onboarding(root, state)
        protected = [unit["id"] for unit in selected
                     if unit["protected"] or unit["id"] in onboarding["protectedUnits"]]
        if protected:
            raise AblationError("protected units cannot be ablated: %s" % ", ".join(protected))
        revision = _current_revision(state)
        removed = list(revision.get("removedUnits", []))
        already_absent = [unit_id for unit_id in requested if unit_id in removed]
        if already_absent:
            raise AblationError("units already absent from this revision: %s" % ", ".join(already_absent))
        original = _safe_artifact(root, state["revisions"][0]["snapshot"]).read_bytes()
        expected_live = _bytes_without_units(original, units, removed)
        if live != expected_live:
            raise AblationError("current checkpoint is not the recorded exact-span composition")
        candidate = _bytes_without_units(original, units, removed + requested)
        if not candidate.strip():
            raise AblationError("whole-file or empty-file ablation is prohibited")
        trial_id = "T%04d" % state["nextTrial"]
        state["nextTrial"] += 1
        candidate_ref = _put_artifact(root, "trials/%s/candidate.bin" % trial_id, candidate)
        before = live.decode("utf-8").splitlines(keepends=True)
        after = candidate.decode("utf-8").splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(before, after, fromfile="accepted/%s" % revision["id"], tofile="candidate/%s" % trial_id))
        diff_ref = _put_artifact(root, "trials/%s/candidate.patch" % trial_id, diff.encode("utf-8"))
        trial = {
            "id": trial_id,
            "status": "staged",
            "unitId": requested[0],
            "unitIds": requested,
            "parentRevision": revision["id"],
            "parentSha256": revision["sha256"],
            "candidateSha256": sha256_bytes(candidate),
            "candidate": candidate_ref,
            "diff": diff_ref,
            "removedUnits": removed + requested,
            "evidence": {},
            "createdAt": utc_now(),
        }
        state["trials"][trial_id] = trial
        state["activeTrial"] = trial_id
        state["status"] = "staged"
        state["nextAction"] = "run fresh paired evaluations and record evidence for each configured model"
        _save_state(root, state)
        _event(root, "trial_staged", trial=trial_id, units=requested,
               parentSha256=revision["sha256"], candidateSha256=trial["candidateSha256"])
        summary = session_summary(root, state)
        summary["trial"] = {key: trial[key] for key in ("id", "unitIds", "parentSha256", "candidateSha256", "candidate", "diff")}
        return summary


def accept_trial(path: Path, trial_id: str, candidate_sha: str) -> Dict[str, Any]:
    target = canonical_target(path)
    root = session_dir(target)
    with SessionLock(root):
        root, state = _open(target)
        if state["status"] != "review_pending":
            raise AblationError("trial is not ready for review")
        trial = _trial(state, trial_id)
        if candidate_sha != trial["candidateSha256"]:
            raise AblationError("explicit candidate hash authorization does not match")
        if set(trial["evidence"]) != set(state["models"]):
            raise AblationError("evidence is incomplete")
        blocked = {model: value["verdict"] for model, value in trial["evidence"].items() if value["verdict"] != "no_regression_observed"}
        if blocked:
            raise AblationError("acceptance blocked by regression or inconclusive evidence: %s" % blocked)
        live = _require_live_head(state)
        candidate = _safe_artifact(root, trial["candidate"]).read_bytes()
        revision = _current_revision(state)
        txid = "X%04d" % state["nextTransaction"]
        state["nextTransaction"] += 1
        pre_ref = _put_artifact(root, "transactions/%s-pre.bin" % txid, live)
        tx = {
            "id": txid,
            "type": "apply",
            "status": "prepared",
            "trial": trial_id,
            "parentSha256": revision["sha256"],
            "candidateSha256": trial["candidateSha256"],
            "preSnapshot": pre_ref,
            "mode": revision["mode"],
            "preparedAt": utc_now(),
        }
        _write_transaction(root, tx)
        state["transaction"] = tx
        state["status"] = "applying"
        _save_state(root, state)
        try:
            _atomic_replace_target(target, candidate, revision["mode"])
            _finalize_apply(root, state)
        except BaseException:
            try:
                current = target.read_bytes()
                if sha256_bytes(current) != revision["sha256"]:
                    _atomic_replace_target(target, live, revision["mode"])
                tx["status"] = "failed_restored"
                tx["failedAt"] = utc_now()
                _write_transaction(root, tx)
                state["transaction"] = None
                state["status"] = "review_pending"
                _save_state(root, state)
            except BaseException:
                state["status"] = "recovery_required"
                _save_state(root, state)
            raise
        return session_summary(root, state)


def reject_trial(path: Path, trial_id: str) -> Dict[str, Any]:
    target = canonical_target(path)
    root = session_dir(target)
    with SessionLock(root):
        root, state = _open(target)
        if state["status"] not in {"staged", "testing", "review_pending"}:
            raise AblationError("there is no rejectable trial")
        trial = _trial(state, trial_id)
        _require_live_head(state)
        trial["status"] = "rejected"
        trial["decidedAt"] = utc_now()
        state["activeTrial"] = None
        state["status"] = "ready"
        state["nextAction"] = "stage one unprotected inventory unit"
        _save_state(root, state)
        _event(root, "trial_rejected", trial=trial_id)
        return session_summary(root, state)


def rollback(path: Path, revision_id: Optional[str] = None) -> Dict[str, Any]:
    target = canonical_target(path)
    root = session_dir(target)
    with SessionLock(root):
        root, state = _open(target)
        if state["status"] != "ready" or state.get("activeTrial"):
            raise AblationError("rollback requires ready state and no active trial")
        live = _require_live_head(state)
        revisions = state["revisions"]
        if len(revisions) < 2 and revision_id is None:
            raise AblationError("no earlier revision to restore")
        wanted = revision_id or revisions[-2]["id"]
        target_revision = next((item for item in revisions if item["id"] == wanted), None)
        if target_revision is None:
            raise AblationError("unknown rollback revision %s" % wanted)
        if target_revision["id"] == state["currentRevision"]:
            raise AblationError("rollback target is already current")
        restored = _safe_artifact(root, target_revision["snapshot"]).read_bytes()
        current_revision = _current_revision(state)
        txid = "X%04d" % state["nextTransaction"]
        state["nextTransaction"] += 1
        pre_ref = _put_artifact(root, "transactions/%s-pre.bin" % txid, live)
        tx = {
            "id": txid,
            "type": "rollback",
            "status": "prepared",
            "targetRevision": wanted,
            "targetSha256": target_revision["sha256"],
            "fromRevision": current_revision["id"],
            "fromSha256": current_revision["sha256"],
            "preSnapshot": pre_ref,
            "preparedAt": utc_now(),
        }
        _write_transaction(root, tx)
        state["transaction"] = tx
        state["status"] = "rolling_back"
        _save_state(root, state)
        try:
            _atomic_replace_target(target, restored, target_revision["mode"])
            _finalize_rollback(root, state)
        except BaseException:
            try:
                if sha256_bytes(target.read_bytes()) != current_revision["sha256"]:
                    _atomic_replace_target(target, live, current_revision["mode"])
                tx["status"] = "failed_restored"
                tx["failedAt"] = utc_now()
                _write_transaction(root, tx)
                state["transaction"] = None
                state["status"] = "ready"
                _save_state(root, state)
            except BaseException:
                state["status"] = "recovery_required"
                _save_state(root, state)
            raise
        return session_summary(root, state)


def reconcile(path: Path) -> Dict[str, Any]:
    target = canonical_target(path)
    root = session_dir(target)
    with SessionLock(root):
        root, state = _open(target)
        if state["status"] == "recovery_required":
            live_sha = sha256_bytes(_target_bytes(state))
            expected = _current_revision(state)["sha256"]
            if live_sha != expected:
                raise AblationError("manual recovery required: live target matches no safe transaction endpoint")
            state["transaction"] = None
            state["status"] = "ready" if state.get("onboarding") else "onboarding"
            _save_state(root, state)
            _event(root, "manual_reconciliation_confirmed", liveSha256=live_sha)
        return session_summary(root, state)


def _guidance_cell(root: Path, state: Dict[str, Any], model: str,
                   summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not summary:
        return {
            "modelId": model,
            "judgeModelId": state["designerModel"],
            "verdict": "untested",
            "candidatePasses": 0,
            "candidateRuns": 0,
            "parentPasses": 0,
            "parentRuns": 0,
            "failedCases": [],
            "inconclusiveCases": [],
        }
    evidence = _read_json(_safe_artifact(root, summary["artifact"]))
    candidate_runs = [value for case in evidence["cases"] for value in case["runs"]]
    parent_runs = [value for case in evidence["cases"] for value in case.get("parentRuns", [])]
    return {
        "modelId": model,
        "judgeModelId": evidence["judgeModelId"],
        "verdict": summary["verdict"],
        "candidatePasses": candidate_runs.count("pass"),
        "candidateRuns": len(candidate_runs),
        "parentPasses": parent_runs.count("pass"),
        "parentRuns": len(parent_runs),
        "failedCases": [case["caseId"] for case in evidence["cases"] if "fail" in case["runs"]],
        "inconclusiveCases": [case["caseId"] for case in evidence["cases"]
                              if "inconclusive" in case["runs"] or "inconclusive" in case.get("parentRuns", [])],
        "suiteSha256": evidence["suiteSha256"],
        "parentSha256": evidence["parentSha256"],
        "candidateSha256": evidence.get("candidateSha256"),
        "repetitions": evidence["repetitions"],
        "limitation": "Scoped evidence for this exact model, checkpoint, and sealed suite only.",
    }


def session_summary(root: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    revision = _current_revision(state)
    original_revision = state["revisions"][0]
    original_size = len(_safe_artifact(root, original_revision["snapshot"]).read_bytes())
    current_size = len(_safe_artifact(root, revision["snapshot"]).read_bytes())
    removed_percent = round(max(0.0, (original_size - current_size) * 100.0 / max(1, original_size)), 2)
    accepted = [item for item in state["revisions"] if item.get("action") == "accepted_ablation"]
    last_ablation_at = accepted[-1]["createdAt"] if accepted else None
    measured_at = utc_now()
    live_sha = None
    drift = None
    try:
        live_sha = sha256_bytes(Path(state["target"]).read_bytes())
        drift = live_sha != revision["sha256"]
    except OSError:
        drift = True
    active = state.get("trials", {}).get(state.get("activeTrial"))
    evidence = {}
    if active:
        evidence = {model: active.get("evidence", {}).get(model, {"verdict": "untested"})["verdict"] for model in state["models"]}
    selected_evidence = active.get("evidence", {}) if active else state.get("baselines", {})
    guidance = [_guidance_cell(root, state, model, selected_evidence.get(model)) for model in state["models"]]
    return {
        "sessionId": state["sessionId"],
        "stateDirectory": str(root),
        "target": state["target"],
        "status": state["status"],
        "nextAction": state.get("nextAction"),
        "currentRevision": state["currentRevision"],
        "currentSha256": revision["sha256"],
        "liveSha256": live_sha,
        "drift": drift,
        "models": state["models"],
        "designerModel": state["designerModel"],
        "repetitions": state["repetitions"],
        "concurrency": state.get("concurrency", 1),
        "suiteSha256": state.get("suiteSha256"),
        "lastAblationAt": last_ablation_at,
        "lastActivityAt": state.get("updatedAt"),
        "baselineComparison": {
            "baselineRevision": original_revision["id"],
            "baselineCapturedAt": original_revision["createdAt"],
            "baselineBytes": original_size,
            "currentRevision": revision["id"],
            "currentRevisionAt": revision["createdAt"],
            "currentBytes": current_size,
            "measuredAt": measured_at,
            "removedPercentFromBaseline": removed_percent,
        },
        "baselineVerdicts": {model: state.get("baselines", {}).get(model, {"verdict": "untested"})["verdict"] for model in state["models"]},
        "activeTrial": active["id"] if active else None,
        "candidateSha256": active["candidateSha256"] if active else None,
        "trialEvidence": evidence,
        "modelGuidance": guidance,
        "inventoryPath": str(root / state["inventory"]["path"]),
        "onboardingPath": str(root / "onboarding.json"),
        "revisionCount": len(state["revisions"]),
    }


def status(path: Path) -> Dict[str, Any]:
    target = canonical_target(path)
    root = session_dir(target)
    with SessionLock(root):
        root, state = _open(target)
        return session_summary(root, state)


def list_sessions() -> Dict[str, Any]:
    base = state_root() / "ablation"
    sessions = []
    if base.is_dir():
        for state_path in sorted(base.glob("*/state.json")):
            try:
                state = _read_json(state_path)
                sessions.append({"sessionId": state.get("sessionId"), "target": state.get("target"), "status": state.get("status"), "updatedAt": state.get("updatedAt")})
            except AblationError as exc:
                sessions.append({"sessionId": state_path.parent.name, "status": "corrupt", "error": str(exc)})
    return {"stateRoot": str(state_root()), "sessions": sessions}


def archive_session(path: Path, output: Path) -> Dict[str, Any]:
    """Create a user-requested private archive. Archiving is never automatic."""
    target = canonical_target(path)
    root = session_dir(target)
    with SessionLock(root):
        root, state = _open(target)
        root = root.resolve(strict=True)
        destination = output.expanduser()
        if destination.exists() or destination.is_symlink():
            raise AblationError("archive destination already exists: %s" % destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = destination.resolve(strict=False)
        if root == destination or root in destination.parents:
            raise AblationError("archive destination must be outside the session directory")
        for item in root.rglob("*"):
            if item == root / ".lock":
                continue
            if item.is_symlink() or (not item.is_dir() and not item.is_file()):
                raise AblationError("session contains an unsafe archive entry: %s" % item)
        fd, temp_name = tempfile.mkstemp(prefix=".context-diet-archive-", dir=str(destination.parent))
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            with tarfile.open(str(temp_path), "w:gz") as archive:
                prefix = "context-diet-ablation-%s" % state["sessionId"]
                for item in sorted(root.rglob("*"), key=lambda value: str(value.relative_to(root))):
                    if item == root / ".lock":
                        continue
                    archive.add(str(item), arcname="%s/%s" % (prefix, item.relative_to(root)), recursive=False)
            os.chmod(temp_path, 0o600)
            os.replace(str(temp_path), str(destination))
            _fsync_dir(destination.parent)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        data = destination.read_bytes()
        return {
            "archived": True,
            "automatic": False,
            "target": str(target),
            "sessionId": state["sessionId"],
            "archive": str(destination),
            "archiveSha256": sha256_bytes(data),
            "bytes": len(data),
            "createdAt": utc_now(),
            "warning": "Archive may contain complete private context, prompts, evidence, and snapshots.",
        }


def _emit(data: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return
    for key in ("status", "target", "currentRevision", "currentSha256", "activeTrial", "candidateSha256", "drift", "concurrency", "lastAblationAt", "lastActivityAt", "nextAction", "inventoryPath", "stateDirectory", "archive", "archiveSha256"):
        if key in data and data[key] is not None:
            print("%s: %s" % (key, data[key]))
    if "reasons" in data:
        if "guidedAblation" in data:
            print("guidedAblation: %s" % data["guidedAblation"])
        if "suggestAblation" in data:
            print("suggestAblation: %s" % data["suggestAblation"])
        print("reasons: %s" % (", ".join(data["reasons"]) or "none"))
    if "baselineVerdicts" in data:
        print("baselines: %s" % json.dumps(data["baselineVerdicts"], sort_keys=True))
    if "baselineComparison" in data:
        comparison = data["baselineComparison"]
        print("baselineDelta: %(removedPercentFromBaseline)s%% removed · %(baselineBytes)s → %(currentBytes)s bytes · measured %(measuredAt)s" % comparison)
    if "trialEvidence" in data and data["trialEvidence"]:
        print("trialEvidence: %s" % json.dumps(data["trialEvidence"], sort_keys=True))
    for cell in data.get("modelGuidance", []):
        print("model: %(modelId)s · %(verdict)s · candidate %(candidatePasses)s/%(candidateRuns)s · parent %(parentPasses)s/%(parentRuns)s" % cell)
    if "sessions" in data:
        print(json.dumps(data, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Checkpointed, bounded-concurrency context ablation")
    sub = parser.add_subparsers(dest="action", required=True)
    detect = sub.add_parser("detect", help="detect aggressive removal intent or candidate risk")
    detect.add_argument("file")
    detect.add_argument("--request", default="")
    detect.add_argument("--candidate")
    detect.add_argument("--json", action="store_true")
    pre = sub.add_parser("preflight", help="on explicit invocation, assess risk and declared model tiers")
    pre.add_argument("file")
    pre.add_argument("--request", default="")
    pre.add_argument("--candidate")
    pre.add_argument("--model-route", action="append", default=[], metavar="PROVIDER/MODEL=TIER")
    pre.add_argument("--json", action="store_true")
    init = sub.add_parser("init", help="create the original checkpoint and onboarding inventory")
    init.add_argument("file")
    init.add_argument("--models", nargs="+", required=True)
    init.add_argument("--designer-model", required=True)
    init.add_argument("--repetitions", type=int, default=3)
    init.add_argument("--concurrency", type=int, default=1,
                      help="maximum inventory units in one trial (default: 1; max: 10)")
    init.add_argument("--trigger", action="append", default=[])
    init.add_argument("--json", action="store_true")
    onboard = sub.add_parser("onboard", help="seal a user-approved suite and protected set")
    onboard.add_argument("file")
    onboard.add_argument("--manifest", required=True)
    onboard.add_argument("--json", action="store_true")
    evidence = sub.add_parser("record-evidence", aliases=["record-baseline", "record-trial"], help="import hash-bound baseline or trial evidence")
    evidence.add_argument("file")
    evidence.add_argument("--evidence", required=True)
    evidence.add_argument("--json", action="store_true")
    stage = sub.add_parser("stage", help="prepare a bounded exact-unit deletion without editing the target")
    stage.add_argument("file")
    stage.add_argument("--unit", required=True, action="append",
                       help="inventory unit; repeat up to the session concurrency")
    stage.add_argument("--json", action="store_true")
    accept = sub.add_parser("accept", help="atomically apply a fully passing candidate")
    accept.add_argument("file")
    accept.add_argument("trial")
    accept.add_argument("--candidate-sha", required=True)
    accept.add_argument("--json", action="store_true")
    reject = sub.add_parser("reject", help="reject the active candidate without target changes")
    reject.add_argument("file")
    reject.add_argument("trial")
    reject.add_argument("--json", action="store_true")
    restore = sub.add_parser("rollback", help="restore an immutable revision as a new reversible revision")
    restore.add_argument("file")
    restore.add_argument("revision", nargs="?")
    restore.add_argument("--json", action="store_true")
    recover = sub.add_parser("reconcile", help="resolve a safely-ended interrupted transaction")
    recover.add_argument("file")
    recover.add_argument("--json", action="store_true")
    show = sub.add_parser("status", help="show resumable progress and evidence")
    show.add_argument("file")
    show.add_argument("--json", action="store_true")
    listing = sub.add_parser("list", help="list local sessions")
    listing.add_argument("--json", action="store_true")
    archive = sub.add_parser("archive", help="manually create a private session archive")
    archive.add_argument("file")
    archive.add_argument("--output", required=True)
    archive.add_argument("--json", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "detect":
            original_path = canonical_target(Path(args.file))
            candidate = canonical_target(Path(args.candidate)).read_bytes() if args.candidate else None
            result = risk_assessment(args.request, original_path.read_bytes(), candidate)
        elif args.action == "preflight":
            original_path = canonical_target(Path(args.file))
            candidate = canonical_target(Path(args.candidate)).read_bytes() if args.candidate else None
            result = preflight(args.request, original_path.read_bytes(), candidate, args.model_route)
        elif args.action == "init":
            result = init_session(Path(args.file), args.models, args.designer_model, args.repetitions,
                                  args.trigger, args.concurrency)
        elif args.action == "onboard":
            result = approve_onboarding(Path(args.file), Path(args.manifest))
        elif args.action in {"record-evidence", "record-baseline", "record-trial"}:
            result = record_evidence(Path(args.file), Path(args.evidence))
        elif args.action == "stage":
            result = stage_trial(Path(args.file), args.unit)
        elif args.action == "accept":
            result = accept_trial(Path(args.file), args.trial, args.candidate_sha)
        elif args.action == "reject":
            result = reject_trial(Path(args.file), args.trial)
        elif args.action == "rollback":
            result = rollback(Path(args.file), args.revision)
        elif args.action == "reconcile":
            result = reconcile(Path(args.file))
        elif args.action == "status":
            result = status(Path(args.file))
        elif args.action == "list":
            result = list_sessions()
        elif args.action == "archive":
            result = archive_session(Path(args.file), Path(args.output))
        else:
            parser.error("unknown action")
            return 2
        _emit(result, getattr(args, "json", False))
        return 0
    except AblationError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
