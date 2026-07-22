#!/usr/bin/env python3
"""Measure context files and manage review-before-mutation Context Diet plans."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LIMIT = 40_000
TOKENS_PER_CHAR = 0.25
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
PLAN_VERSION = 2
ACTIONS = {"keep", "condense", "externalize", "retire", "delete"}


@dataclass
class Section:
    title: str
    level: int
    chars: int
    approxTokens: int
    lineStart: int


def approxTokens(chars: int) -> int:
    return int(round(chars * TOKENS_PER_CHAR))


def splitSections(text: str, atLevel: int = 2) -> list[Section]:
    lines = text.splitlines(keepends=True)
    sections: list[Section] = []
    title, level, buf, start = "(preamble)", 0, [], 1

    def flush() -> None:
        body = "".join(buf)
        if body or sections:
            sections.append(Section(title, level, len(body), approxTokens(len(body)), start))

    for idx, line in enumerate(lines, start=1):
        match = HEADING.match(line)
        if match and len(match.group(1)) == atLevel:
            flush()
            title, level, buf, start = match.group(2).strip(), len(match.group(1)), [line], idx
        else:
            buf.append(line)
    flush()
    return sections


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(path: Path, limit: int, atLevel: int = 2) -> dict:
    text = path.read_text(encoding="utf-8")
    total = len(text)
    sections = splitSections(text, atLevel)
    return {
        "file": str(path), "totalChars": total, "approxTokens": approxTokens(total),
        "limit": limit, "overLimit": total > limit, "overBy": max(0, total - limit),
        "headroom": max(0, limit - total), "sectionCount": len(sections),
        "sections": [asdict(s) for s in sections],
        "ranked": [asdict(s) for s in sorted(sections, key=lambda s: s.chars, reverse=True)],
    }


def defaultPlanPath(path: Path) -> Path:
    return path.parent / ".context-diet" / f"{path.name}.plan.json"


def readPlan(planPath: Path) -> dict:
    if not planPath.is_file():
        raise ValueError(f"plan not found: {planPath}")
    return json.loads(planPath.read_text(encoding="utf-8"))


def validatePlan(plan: dict, source: Path, requireReady: bool = False) -> list[str]:
    errors = []
    if plan.get("version") != PLAN_VERSION:
        errors.append(f"expected plan version {PLAN_VERSION}")
    if Path(plan.get("source", "")).resolve() != source.resolve():
        errors.append("plan targets a different source file")
    if plan.get("sourceSha256") != digest(source):
        errors.append("plan is stale: source hash changed")
    for action in plan.get("actions", []):
        if action.get("action") not in ACTIONS:
            errors.append(f"invalid action for {action.get('id', '<unknown>')}")
        for key in ("id", "itemId", "action", "reason", "confidence", "estimatedSavings"):
            if key not in action:
                errors.append(f"action missing {key}: {action.get('id', '<unknown>')}")
    if requireReady:
        if plan.get("status") != "proposed":
            errors.append('plan is not ready: expected status "proposed"')
        inventory = plan.get("inventory", [])
        actions = plan.get("actions", [])
        if not inventory:
            errors.append("inventory is empty")
        if not actions:
            errors.append("actions are empty")
        itemIds = [item.get("id") for item in inventory]
        if None in itemIds or len(itemIds) != len(set(itemIds)):
            errors.append("inventory ids must be present and unique")
        for item in inventory:
            for key in ("id", "kind", "text", "protected"):
                if key not in item:
                    errors.append(f"inventory item missing {key}: {item.get('id', '<unknown>')}")
        actionIds = [action.get("id") for action in actions]
        if None in actionIds or len(actionIds) != len(set(actionIds)):
            errors.append("action ids must be present and unique")
        protectedIds = {item.get("id") for item in inventory if item.get("protected") is True}
        for action in actions:
            itemId = action.get("itemId")
            if itemId not in itemIds:
                errors.append(f"action references unknown inventory item: {action.get('id', '<unknown>')}")
            if itemId in protectedIds and action.get("action") in {"retire", "delete"}:
                errors.append(f"protected item cannot be {action.get('action')}: {itemId}")
        recommendation = plan.get("recommendation")
        if recommendation not in {"safe", "recommended", "aggressive"}:
            errors.append("plan recommendation is incomplete")
        floor = plan.get("protectedFloorChars")
        if not isinstance(floor, int) or floor < 0:
            errors.append("protected floor is incomplete")
        originalChars = plan.get("original", {}).get("chars")
        tiers = plan.get("tiers", {})
        reductions = []
        for name in ("safe", "recommended", "aggressive"):
            tier = tiers.get(name, {})
            required = ("strategy", "reductionPct", "savedChars", "finalChars", "actionIds",
                        "protectedLoss", "inlineRetention", "corpusRetention", "artifact",
                        "artifactSha256", "linkedFiles")
            if any(key not in tier for key in required):
                errors.append(f"{name} tier is incomplete")
                continue
            saved, final, pct = tier["savedChars"], tier["finalChars"], tier["reductionPct"]
            if not all(isinstance(value, (int, float)) for value in (saved, final, pct)):
                errors.append(f"{name} tier size values must be numeric")
                continue
            reductions.append(float(pct))
            if not 0 <= pct <= 100:
                errors.append(f"{name} reduction must be between 0 and 100")
            if not isinstance(originalChars, int) or saved != originalChars - final:
                errors.append(f"{name} tier size math is inconsistent")
            elif originalChars and abs(pct - (saved / originalChars * 100)) > 0.2:
                errors.append(f"{name} reduction percentage is inconsistent")
            if isinstance(floor, int) and final < floor:
                errors.append(f"{name} tier falls below protected floor")
            unknownActions = set(tier["actionIds"]) - set(actionIds)
            if unknownActions:
                errors.append(f"{name} tier references unknown actions")
            if tier["protectedLoss"]:
                errors.append(f"{name} tier loses protected context")
            artifact = tier["artifact"]
            if not isinstance(artifact, str) or len(artifact) != final:
                errors.append(f"{name} artifact length does not match finalChars")
            elif hashlib.sha256(artifact.encode("utf-8")).hexdigest() != tier["artifactSha256"]:
                errors.append(f"{name} artifact hash is invalid")
            for linked in tier["linkedFiles"]:
                if any(key not in linked for key in ("path", "content", "sha256")):
                    errors.append(f"{name} linked file is incomplete")
                    continue
                linkedPath = Path(linked["path"])
                if linkedPath.is_absolute() or ".." in linkedPath.parts:
                    errors.append(f"{name} linked file path must stay under the source directory")
                content = linked["content"]
                if hashlib.sha256(content.encode("utf-8")).hexdigest() != linked["sha256"]:
                    errors.append(f"{name} linked file hash is invalid: {linked['path']}")
        if len(reductions) == 3 and reductions != sorted(reductions):
            errors.append("tier reductions must be monotonic")
    return errors


def writeJson(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def initPlan(source: Path, planPath: Path, goal: str, baseline: dict,
             replan: bool = False) -> tuple[dict, bool]:
    if planPath.is_file():
        existing = readPlan(planPath)
        errors = validatePlan(existing, source)
        requestedGoal = goal or "Optimize recurring context cost"
        if existing.get("goal") != requestedGoal and not replan:
            raise ValueError("saved plan has a different goal; rerun with --replan")
        if errors and not replan:
            raise ValueError("saved plan is stale or invalid; rerun with --replan: " + "; ".join(errors))
        if not replan:
            return existing, False
    plan = {
        "version": PLAN_VERSION,
        "status": "draft",
        "source": str(source.resolve()),
        "sourceSha256": digest(source),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "goal": goal or "Optimize recurring context cost",
        "original": {"chars": baseline["totalChars"], "approxTokens": baseline["approxTokens"]},
        "recommendation": None,
        "protectedFloorChars": None,
        "inventory": [],
        "actions": [],
        "tiers": {},
    }
    writeJson(planPath, plan)
    return plan, True


def renderReport(data: dict) -> str:
    status = "OVER LIMIT" if data["overLimit"] else "within limit"
    lines = [f"Context Diet Report — {Path(data['file']).name}", "═" * 64, "",
             f"Total: {data['totalChars']:,} chars (~{data['approxTokens']:,} tok)  ·  "
             f"limit {data['limit']:,}  ·  {status}"]
    lines.append(f"Over by: {data['overBy']:,} chars." if data["overLimit"]
                 else f"Headroom: {data['headroom']:,} chars.")
    lines += [f"Sections: {data['sectionCount']}", "", "Largest sections (optimization targets)",
              "─" * 64, f"{'chars':>7}  {'~tok':>6}  {'ln':>5}  section"]
    for section in data["ranked"][:15]:
        title = section["title"] if len(section["title"]) <= 38 else section["title"][:37] + "…"
        lines.append(f"{section['chars']:>7,}  {section['approxTokens']:>6,}  "
                     f"{section['lineStart']:>5}  {title}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure and manage an agent-context optimization plan.")
    parser.add_argument("file")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--level", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--plan", help="plan path; defaults to .context-diet/<file>.plan.json")
    parser.add_argument("--goal", default="")
    parser.add_argument("--replan", action="store_true", help="replace a stale plan or changed goal")
    parser.add_argument("--import-proposal", metavar="JSON", help="merge and validate a semantic proposal")
    parser.add_argument("--tier", choices=("safe", "recommended", "aggressive"),
                        help="authorized tier for --checkpoint")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--init-plan", action="store_true")
    mode.add_argument("--proposal-template", action="store_true")
    mode.add_argument("--check-plan", action="store_true")
    mode.add_argument("--checkpoint", action="store_true")
    mode.add_argument("--complete", action="store_true")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    source = Path(args.file)
    if not source.is_file():
        print(f"error: {source} not found", file=sys.stderr)
        return 2
    planPath = Path(args.plan) if args.plan else defaultPlanPath(source)
    baseline = measure(source, args.limit, args.level)

    if args.proposal_template:
        tier = {"strategy": "", "reductionPct": 0, "savedChars": 0,
                "finalChars": baseline["totalChars"], "actionIds": [],
                "protectedLoss": [], "inlineRetention": 100, "corpusRetention": 100,
                "artifact": source.read_text(encoding="utf-8"),
                "artifactSha256": digest(source), "linkedFiles": []}
        print(json.dumps({
            "inventory": [{"id": "", "kind": "", "text": "", "protected": False}],
            "actions": [{"id": "", "itemId": "", "action": "condense", "reason": "",
                         "confidence": 0.0, "estimatedSavings": 0}],
            "tiers": {name: dict(tier) for name in ("safe", "recommended", "aggressive")},
            "recommendation": "recommended", "protectedFloorChars": baseline["totalChars"],
        }, indent=2))
        return 0

    if args.init_plan:
        try:
            plan, created = initPlan(source, planPath, args.goal, baseline, args.replan)
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"plan": str(planPath), "status": plan["status"],
                          "created": created, "reused": not created,
                          "sourceFresh": not validatePlan(plan, source)}, indent=2))
        return 0
    if args.import_proposal:
        try:
            plan = readPlan(planPath)
            proposal = json.loads(Path(args.import_proposal).read_text(encoding="utf-8"))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        for key in ("inventory", "actions", "tiers", "recommendation", "protectedFloorChars"):
            if key in proposal:
                plan[key] = proposal[key]
        plan["status"] = "proposed"
        errors = validatePlan(plan, source, requireReady=True)
        if errors:
            print(json.dumps({"imported": False, "errors": errors}, indent=2))
            return 1
        writeJson(planPath, plan)
        print(json.dumps({"imported": True, "plan": str(planPath)}, indent=2))
        return 0
    if args.check_plan:
        try:
            plan = readPlan(planPath)
            errors = validatePlan(plan, source, requireReady=True)
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"plan": str(planPath), "fresh": not errors, "errors": errors}, indent=2))
        return 1 if errors else 0
    if args.checkpoint:
        if not args.tier:
            print("error: --checkpoint requires --tier", file=sys.stderr)
            return 2
        plan = readPlan(planPath)
        errors = validatePlan(plan, source, requireReady=True)
        if errors:
            print("error: " + "; ".join(errors), file=sys.stderr)
            return 2
        backup = planPath.with_suffix(planPath.suffix + ".backup")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup)
        linkedBackups = []
        backupRoot = planPath.parent / f"{planPath.stem}.backup-files"
        for linked in plan["tiers"][args.tier]["linkedFiles"]:
            linkedPath = source.parent / linked["path"]
            record = {"path": linked["path"], "existed": linkedPath.is_file()}
            if linkedPath.is_file():
                linkedBackup = backupRoot / linked["path"]
                linkedBackup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(linkedPath, linkedBackup)
                record.update({"backup": str(linkedBackup), "sha256": digest(linkedBackup)})
            linkedBackups.append(record)
        plan["checkpoint"] = {"path": str(backup), "sha256": digest(backup),
                              "linkedFiles": linkedBackups}
        plan["authorizedTier"] = args.tier
        plan["status"] = "authorized"
        writeJson(planPath, plan)
        print(json.dumps(plan["checkpoint"], indent=2))
        return 0
    if args.complete:
        plan = readPlan(planPath)
        if plan.get("status") != "authorized":
            print('error: plan is not authorized; run --checkpoint after user approval', file=sys.stderr)
            return 2
        checkpoint = plan.get("checkpoint", {})
        backup = Path(checkpoint.get("path", ""))
        if not backup.is_file():
            print("error: checkpoint not found", file=sys.stderr)
            return 2
        tierName = plan.get("authorizedTier")
        tier = plan.get("tiers", {}).get(tierName, {})
        if tier.get("artifactSha256") != digest(source):
            print(f"error: source does not match authorized {tierName} artifact", file=sys.stderr)
            return 2
        for linked in tier.get("linkedFiles", []):
            linkedPath = source.parent / linked["path"]
            if not linkedPath.is_file() or digest(linkedPath) != linked["sha256"]:
                print(f"error: linked file does not match authorized artifact: {linked['path']}",
                      file=sys.stderr)
                return 2
        before = measure(backup, args.limit, args.level)
        after = baseline
        plan["status"] = "applied"
        plan["result"] = {"sourceSha256": digest(source), "chars": after["totalChars"],
                          "reduction": before["totalChars"] - after["totalChars"],
                          "reductionPct": round((before["totalChars"] - after["totalChars"])
                                                / before["totalChars"] * 100, 1)
                          if before["totalChars"] else 0}
        writeJson(planPath, plan)
        print(json.dumps(plan["result"], indent=2))
        return 0

    print(json.dumps(baseline, indent=2) if args.json else renderReport(baseline))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
