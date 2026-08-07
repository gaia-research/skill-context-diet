---
name: context-diet
description: >-
  Measure and compact an oversized agent-context file (CLAUDE.md, .cursorrules,
  AGENTS.md, a system prompt) without losing rules, or safely run reversible
  bounded, reversible ablation when intentional/aggressive context removal is
  requested. Triggers: "CLAUDE.md too big", "over the char limit", "context file
  too large", "compact my agent config", "trim CLAUDE.md", "delete context",
  "rebuild instructions from scratch", "context diet", "/context-diet".
version: 1.2.0
---

# context-diet

Measure context size, preserve rules during ordinary compaction, and fail over to checkpointed guided ablation before any intentional rule loss.

## Route the request before editing

Use normal measurement/bake-off for rule-preserving work:

```bash
python3 context_diet.py FILE [--limit 40000] [--json]
```

Use guided ablation explicitly for `/context-diet ablate FILE`. On an explicit `/context-diet` invocation, a host may first run suggestion-only pre-flight with exact route/tier facts it already knows:

```bash
python3 context_diet.py ablate preflight FILE \
  --model-route provider/frontier-model=big --json
```

A declared high-tier route may justify proactively offering ablation, but pre-flight must not run outside a user invocation, infer tiers from display names, create a session, or edit the target.

Also route automatically, **before modifying the target**, when any of these is true:

- the user asks to delete, empty, truncate, disable, replace, or rebuild the context file;
- a proposal intentionally retires a complete rule/directive/guardrail;
- a candidate removes multiple inventory units or any protected unit;
- before a trustworthy inventory exists, a candidate removes at least 20% of source bytes, removes multiple Markdown blocks, or empties the file;
- a faithfulness audit reports a missing/weakened rule rather than 100% corpus retention.

Run the deterministic check when request text or a candidate is available:

```bash
python3 context_diet.py ablate detect FILE --request "USER REQUEST" --json
python3 context_diet.py ablate detect FILE --candidate CANDIDATE --json
```

These are conservative product guardrails, not scientific safety thresholds. Condensation or externalization that retains 100% of the inventoried corpus does not itself trigger ablation.

When escalation occurs, state the exact trigger, do not edit the live file, and read [ABLATION.md](./ABLATION.md) completely before orchestration.

## Normal compaction path

1. Measure the file. Character count is authoritative; tokens are an approximation.
2. Extract an exhaustive atomic rule inventory and identify CI/incident, authorization, safety, exact-literal, preference, and routing constraints as protected.
3. Produce review-only candidates for externalize+link, condense, telegraphic, and hybrid strategies.
4. Adversarially classify every original rule `present`, `weakened`, or `missing` against each complete candidate corpus, including linked files.
5. Disqualify over-limit candidates and any candidate with a weakened/missing load-bearing rule.
6. Show the winner and diff. Apply only after user review using the host's normal file-edit flow.

Externalization is not deletion: leave an inline invariant and resolvable one-hop link, and include the linked file in faithfulness scoring. Re-derive protected sections for each repository; examples from another repository are not a universal set.

See [METHODOLOGY.md](./METHODOLOGY.md) and the frozen [WORKFLOW.md](./WORKFLOW.md) Lab 001 artifact.

## Guided ablation path

The Python controller, not model prose, owns mutation and offsets:

```bash
# 1. Exact original checkpoint + local inventory
python3 context_diet.py ablate init FILE \
  --designer-model provider/capable-model \
  --models provider/model-a provider/model-b --repetitions 3 \
  --concurrency 1

# 2. Seal a user-approved manifest after provider/cost/privacy disclosure
python3 context_diet.py ablate onboard FILE --manifest MANIFEST.json

# 3. Import fresh-context baselines for every exact configured model
python3 context_diet.py ablate record-evidence FILE --evidence BASELINE.json

# 4. Prepare one locally derived deletion by default; live FILE is unchanged
python3 context_diet.py ablate stage FILE --unit CD-0012 --json
# With an explicitly higher session concurrency, repeated units form one batch candidate
python3 context_diet.py ablate stage FILE --unit CD-0012 --unit CD-0017 --json

# 5. Import paired parent/candidate results one cell or bundle at a time
python3 context_diet.py ablate record-evidence FILE --evidence TRIAL.json

# 6. Explicit decision; only accept mutates FILE
python3 context_diet.py ablate accept FILE T0001 --candidate-sha SHA256
python3 context_diet.py ablate reject FILE T0001

# 7. Resume/recover/restore
python3 context_diet.py ablate status FILE --json
python3 context_diet.py ablate reconcile FILE
python3 context_diet.py ablate rollback FILE R0000
# Manual only; may contain the complete private context
python3 context_diet.py ablate archive FILE --output session.tar.gz --json
```

### Onboarding requirements

Present one compact review card containing target/checkpoint hash, exact capable designer/judge model, exact tested model routes, proposed protected units and 3–7 repository-specific cases, repetitions/expected call count, and provider/local-artifact disclosure. Names such as “Opus”, “Sol”, or “Sonnet” are display labels only; never infer or substitute an exact route.

Have the capable model propose an over-complete manifest from the immutable original and controller inventory, then perform an independent adversarial coverage pass. User approval must be bound to the source and manifest content. The controller will not allow auto-protected units to be unprotected.

### Evaluation requirements

Use fresh isolated contexts. When supported, use bundled `ablation.workflow.js` with snapshot content and sealed cases; never ask subject models to inspect or edit the live target. The workflow selects each exact model explicitly, preserves null/unavailable coverage, bounds concurrency, and uses the disclosed capable model as semantic judge. If exact routing/workflows are unavailable, allow status/artifact inspection but mark the cell `inconclusive` and block acceptance—never fall back to the current session model.

Default to one unit for clean attribution. Advanced users may set immutable session concurrency from 1–10 and repeat `--unit` to test that bounded batch as one candidate. This does not permit simultaneous writes: the whole batch shares one evidence gate and atomic decision. Explain that higher concurrency weakens attribution. The next candidate compares against the latest accepted checkpoint; accepted trial evidence is promoted as that checkpoint's baseline.

### Guidance language

Report per exact model only `no_regression_observed`, `regression_observed`, or `inconclusive`. Include exact model and judge IDs, suite/parent/candidate hashes, repetitions, pass counts, failed cases, and missing coverage.

Say “No regression was observed in N paired runs; this exact model may tolerate this omission under this sealed suite.” Never claim a rule is universally safe, infer model capability/rank, or generalize to another version, family label, repository, harness, or production context. Any required-model regression, baseline failure, timeout, route unavailability, missing case, or uncertain judgment blocks acceptance.

### Authorization boundary

The original request, onboarding approval, successful tests, or a model recommendation is **not** file-write authorization. Acceptance requires the user to identify the trial and exact candidate SHA. There is no force/override flag.

`test`/`stage`/`reject` never modify the target. Accept and rollback verify live/artifact hashes, create fresh pre-write snapshots, journal intent, atomically replace, verify, and restore on failure. Unrelated drift, corruption, unsafe symlinks, and ambiguous interrupted transactions fail closed. Never use `git reset` or `git checkout` for rollback.

`status --json` must surface `lastAblationAt`, `lastActivityAt`, and the original-baseline byte percentage with baseline/current/measurement timestamps. `archive` is always an explicit user action; never schedule archives, uploads, retention, or deletion.

## Invocation spelling

Hosts may expose `/context-diet`. Pi's native spelling is `/skill:context-diet`; map either spelling to the same flow. A plain invocation measures normally unless a persisted session for the target is active, in which case show `ablate status` and offer to resume it first.
