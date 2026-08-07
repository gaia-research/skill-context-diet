# context-diet

**Your `CLAUDE.md` is over the limit. Which rules is the harness about to silently drop?**

Claude Code may truncate CLAUDE.md past 40,000 chars. Boss, run /context-diet CLAUDE.md first—compact rules, then make bounded context ablation face evidence.

<img width="1672" height="941" alt="Generated image 3" src="https://github.com/user-attachments/assets/6b2c2aa7-7294-4e53-81bf-72cfd1cd8817" />

Claude Code warns past **40,000 characters** and may truncate beyond it — quietly disabling
whatever rules fell past the cutoff. The same is true for any agent-context file: `.cursorrules`,
`AGENTS.md`, a raw system prompt. `context-diet` measures where the budget goes, section by
section, then compacts the file under the limit **while proving no rule was lost**.

```bash
bash <(curl -sL https://raw.githubusercontent.com/gaia-research/skill-context-diet/main/install.sh)
```

No pip or npm. The analyzer and reversible ablation controller are pure Python stdlib (+matplotlib for charts, optional).

---

## What it looks like

```
Context Diet Report — CLAUDE.md
════════════════════════════════════════════════════════════════

Total: 49,687 chars (~12,422 tok)  ·  limit 40,000  ·  OVER LIMIT
Over by 9,687 chars — must shed at least this to fit.
Sections: 36

Largest sections (compaction targets)
────────────────────────────────────────────────────────────────
  chars    ~tok     ln  section
───────  ──────  ─────  ──────────────────────────────
  3,994     998    216  Programmatic-First Policy
  3,856     964    486  Curation Guidelines
  3,848     962    411  Known Badges Issues (Core Implementat…
  3,823     956    110  Fixed-nav clearance — every top-level…
  3,325     831    435  Known Skill Explorer Issues
```

That's the measurement. The skill then runs a **bake-off** of compaction strategies and applies
the one that shrinks the most *without losing a single rule*.

---

## Why "without losing a rule" is the hard part

An agent-context file isn't prose — it's mostly guardrails, many codified after a specific
incident ("codified after the 2026-XX-XX outage…"). Delete the wrong paragraph and an agent
ships a state that breaks CI, and the next agent works around it, and the drift is irreversible.

So compaction here is a **two-objective** problem:

1. **Reduce size** under the limit.
2. **Retain 100% of rules** — measured, not assumed.

`context-diet` extracts a ground-truth **rule inventory** from the original, generates several
compaction candidates, then **adversarially audits** each one — classifying every rule as
present / weakened / missing against the result (including any linked files). The winner is the
qualified candidate with the highest faithfulness. Anything that drops a load-bearing rule is
disqualified outright.

---

## Compaction strategies

| Strategy | What it does |
|---|---|
| **Externalize + link** | Move large playbooks to linked files; leave a stub = invariant + pointer |
| **Condense in place** | Strip retro/anecdote prose, bullet-ify, keep every rule; no new files |
| **Telegraphic** | Aggressive lexical compression of non-load-bearing prose; keep all literals |
| **Hybrid** | Externalize the largest, condense the mid-size, keep enforced sections verbatim |

Externalization doesn't delete — it moves detail one hop away into a linked file, so the rule
still counts as present. The report separates **in-context size** from **total-corpus size** so
the trade-off is explicit.

---

## Usage

```bash
# Measure any context file
python3 context_diet.py CLAUDE.md
python3 context_diet.py .cursorrules --limit 40000
python3 context_diet.py path/to/system-prompt.md --json > baseline.json

# From an agent conversation (after install)
/context-diet CLAUDE.md
```

The `--json` baseline feeds the bake-off workflow and the chart generator.

### Intentional context removal: guided ablation

Normal compaction retains every rule. Requests to delete/rebuild context, omit protected rules, remove multiple inventoried blocks, or make an unaudited reduction of at least 20% are routed to a separate fail-closed mode. On an explicit `/context-diet` invocation, pre-flight can also notice host-declared high-tier routes and offer ablation before the user asks for a destructive edit—it suggests; it never starts a session or edits a file:

```bash
# Invocation-scoped suggestion using tier facts supplied by the host
python3 context_diet.py ablate preflight CLAUDE.md \
  --model-route provider/frontier-model=big --json

# Original backup + deterministic block inventory (no target edit)
python3 context_diet.py ablate init CLAUDE.md \
  --designer-model provider/capable-model \
  --models provider/model-a provider/model-b --repetitions 3 \
  --concurrency 1

# After reviewing/approving the onboarding manifest and baseline evidence
python3 context_diet.py ablate onboard CLAUDE.md --manifest manifest.json
python3 context_diet.py ablate record-evidence CLAUDE.md --evidence baseline.json

# One deletion candidate at a time by default; still no target edit
python3 context_diet.py ablate stage CLAUDE.md --unit CD-0012 --json

# Advanced: with a higher init concurrency, test a bounded batch together
python3 context_diet.py ablate stage CLAUDE.md \
  --unit CD-0012 --unit CD-0017 --json
python3 context_diet.py ablate record-evidence CLAUDE.md --evidence trial.json

# The only candidate-apply path requires trial + exact hash authorization
python3 context_diet.py ablate accept CLAUDE.md T0001 --candidate-sha <sha256>
python3 context_diet.py ablate rollback CLAUDE.md R0000
```

State and exact snapshots live outside Git by default under `$CONTEXT_DIET_STATE_DIR`, `$XDG_STATE_HOME/context-diet`, or `~/.local/state/context-diet`. Progress resumes across sessions. `status` reports the last accepted ablation, last session activity, and the byte percentage removed from the original baseline, with baseline/current/measurement timestamps so the comparison has a specific time frame.

Concurrency means **units combined into one candidate trial**, not simultaneous writes. It defaults to one and is fixed for the session. Raising it trades causal attribution for speed; the same protected-unit, evidence, explicit-acceptance, and rollback gates apply to the whole batch.

The original is checkpointed before model work; staging/testing/rejection are read-only; apply and rollback are hash-checked, journaled, atomic, and reversible. Archives are manual and may contain the full private context:

```bash
python3 context_diet.py ablate archive CLAUDE.md \
  --output "$HOME/context-diet-archives/claude-ablation.tar.gz" --json
```

Nothing auto-archives, rotates, uploads, or deletes session state.

The bundled `ablation.workflow.js` can run bounded exact-model simulations in environments with dynamic workflow/model routing. Unavailable routes remain inconclusive and never fall back. Results are scoped as “no regression observed for this exact model and sealed suite,” never as proof that a rule or model family is universally safe. Exact routes and tiers must be declared rather than guessed from labels such as Opus, Sol, or Sonnet. See [ABLATION.md](./ABLATION.md) for onboarding/evidence schemas, privacy disclosure, recovery, and limitations.

Pi invokes the installed skill as `/skill:context-diet`; hosts may provide the shorter `/context-diet` alias.

---

### Boundary/source table
| Layer | Documented boundary |
|---|---|
| Local tool | Analyzes context files; the controller owns snapshots, validation, evidence gates, atomic apply, and rollback. See [ABLATION.md](./ABLATION.md). |
| Host | Supplies exact model routing and model-aware evidence; unavailable routes remain inconclusive and block acceptance. See [SKILL.md](./SKILL.md) and [WORKFLOW.md](./WORKFLOW.md). |
| Scope | The repository documents file invocation plus host-supplied routing/evidence; additional integrations are outside this documented scope. |

---

## Reproducible methodology

This tool is the packaged output of **Context Diet — Lab 001** (a Gaia Research benchmark). The
full paper-style protocol — metrics, procedure, how to replay on a different context type, and
threats to validity — is in [METHODOLOGY.md](./METHODOLOGY.md).

The inventory and faithfulness scoring are the **reproducible control**: candidate wording varies
run to run, but *which rules must survive* does not.

---

## Requirements

- **Python 3.8+** — analyzer and ablation controller are pure stdlib.
- **A host with exact model routing** (optional) — required only for multi-model ablation evidence.
- **matplotlib** (optional) — only for the before/after charts.

---

## FAQ

| Question | Answer |
|---|---|
| **What's the 40,000-character limit?** | Claude Code warns past 40k chars in `CLAUDE.md` and may truncate beyond it; the risk applies to other agent-context files too. |
| **What counts as "a rule"?** | Imperatives, guardrails, forbidden patterns, ordered procedures, and literal commands are inventoried before compaction. |
| **How does it know a rule survived?** | It rescans the compacted file and linked files, classifying each inventoried rule present, weakened, or missing. |
| **Won't externalization just move the problem?** | Reports separate in-context size from total-corpus size; linked rules remain available to the agent. |
| **Which compaction strategy should I use?** | The bake-off compares externalize, condense, telegraphic, and hybrid, then returns the highest-faithfulness candidate under the limit. |
| **Can I use it on non-Claude files?** | Yes: `.cursorrules`, `AGENTS.md`, raw system prompts, or Markdown files; pass `--limit` for your budget. |
| **Does it need an API key?** | No for measurement, state, rollback, or archive; compaction and model-aware evidence use models configured by the host. |
| **Can it test several removals together?** | Yes, with `init --concurrency N`: one bounded candidate, one evidence gate, and one atomic accept/rollback. |
| **When did I last ablate, and how much is gone?** | `ablate status FILE --json` reports last activity, last ablation, baseline comparison, percentage removed, and timestamps. |
| **How do I install it?** | Run `bash <(curl -sL https://raw.githubusercontent.com/gaia-research/skill-context-diet/main/install.sh)`. |
| **What's the methodology?** | See [METHODOLOGY.md](./METHODOLOGY.md) for metrics, procedure, replay protocol, and threats to validity. |
| **What is context ablation?** | Intentional, bounded omission tested through evidence gates—not ordinary rule-preserving compaction. Choose an omission; test it within scope. |
| **How do I reduce CLAUDE.md without changing rules?** | Inventory rules, run the compaction bake-off, and accept only a candidate preserving every inventoried rule. Keep the guardrails sharp. |
| **How do I reduce AI-agent context bloat?** | Measure `CLAUDE.md`, `.cursorrules`, `AGENTS.md`, or a raw system prompt, then compact under your character limit. No fuss. |
| **How do I undo accepted guided ablation?** | Run `python3 context_diet.py ablate rollback CLAUDE.md R0000` in a guided-ablation session to restore the selected revision. |
| **Does context-diet edit files in place?** | Measurement and ordinary compaction are review-only; guided ablation applies only after evidence and exact candidate-SHA acceptance. |
| **Does evidence prove a rule is safe to remove?** | No. Evidence covers only the exact route, checkpoint, sealed suite, and candidate SHA—not universal safety. Keep your guardrails sharp. |

---

## License

MIT — see [LICENSE](./LICENSE). Part of the [Gaia Research](https://github.com/gaia-research) ecosystem.
