# context-diet

**Your `CLAUDE.md` is over the limit. Which rules is the harness about to silently drop?**

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

Normal compaction retains every rule. Requests to delete/rebuild context, omit protected rules, remove multiple inventoried blocks, or make an unaudited reduction of at least 20% are routed to a separate fail-closed mode:

```bash
# Original backup + deterministic block inventory (no target edit)
python3 context_diet.py ablate init CLAUDE.md \
  --designer-model provider/capable-model \
  --models provider/model-a provider/model-b --repetitions 3

# After reviewing/approving the onboarding manifest and baseline evidence
python3 context_diet.py ablate onboard CLAUDE.md --manifest manifest.json
python3 context_diet.py ablate record-evidence CLAUDE.md --evidence baseline.json

# One deletion candidate at a time; still no target edit
python3 context_diet.py ablate stage CLAUDE.md --unit CD-0012 --json
python3 context_diet.py ablate record-evidence CLAUDE.md --evidence trial.json

# The only candidate-apply path requires trial + exact hash authorization
python3 context_diet.py ablate accept CLAUDE.md T0001 --candidate-sha <sha256>
python3 context_diet.py ablate rollback CLAUDE.md R0000
```

State and exact snapshots live outside Git by default under `$CONTEXT_DIET_STATE_DIR`, `$XDG_STATE_HOME/context-diet`, or `~/.local/state/context-diet`. Progress resumes across sessions. The original is checkpointed before model work; staging/testing/rejection are read-only; apply and rollback are hash-checked, journaled, atomic, and reversible.

The bundled `ablation.workflow.js` can run bounded exact-model simulations in hosts with dynamic workflow/model routing. Unavailable routes remain inconclusive and never fall back. Results are scoped as “no regression observed for this exact model and sealed suite,” never as proof that a rule or model family is universally safe. See [ABLATION.md](./ABLATION.md) for onboarding/evidence schemas, privacy disclosure, recovery, and limitations.

Pi invokes the installed skill as `/skill:context-diet`; hosts may provide the shorter `/context-diet` alias.

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
| **What's the 40,000-character limit?** | Claude Code warns past 40k chars in `CLAUDE.md` and may silently truncate beyond it. Same risk applies to any agent-context file (`.cursorrules`, `AGENTS.md`, system prompts). |
| **What counts as "a rule"?** | Any imperative or guardrail — MUST/SHOULD statements, forbidden patterns, ordered procedures, literal command strings. `context-diet` extracts these into an inventory before compacting. |
| **How does it know a rule survived?** | It re-scans the compacted file (and any linked files) for each rule in the inventory and classifies it as **present**, **weakened**, or **missing**. A candidate that drops any load-bearing rule is disqualified. |
| **Won't externalization just move the problem?** | The report separates **in-context size** from **total-corpus size**, so the trade-off is explicit. Externalized rules still count as present because the agent can follow the link. |
| **Does it edit my `CLAUDE.md` in place?** | Measurement and ordinary candidates are review-only. Guided ablation writes only after passing locked evidence and explicit trial+candidate-hash acceptance; it checkpoints first and supports exact rollback. |
| **Which compaction strategy should I use?** | Let the bake-off pick. It runs all four (externalize, condense, telegraphic, hybrid) and returns the highest-faithfulness candidate under the limit. |
| **Can I use it on non-Claude files?** | Yes. It's a plain text analyzer — works on `.cursorrules`, `AGENTS.md`, raw system prompts, or any Markdown file. Pass `--limit` for your target budget. |
| **Does it need an API key?** | No for measurement/state/rollback. Compaction and model-aware ablation evidence use the models already configured in the host; missing exact routes stay inconclusive. |
| **How do I install it?** | `bash <(curl -sL https://raw.githubusercontent.com/gaia-research/skill-context-diet/main/install.sh)` — auto-detects your skills dir. |
| **What's the methodology?** | See [METHODOLOGY.md](./METHODOLOGY.md) — full metrics, procedure, replay protocol, and threats to validity. |

---

## License

MIT — see [LICENSE](./LICENSE). Part of the [Gaia Research](https://github.com/gaia-research) ecosystem.
