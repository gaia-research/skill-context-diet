# context-diet

**Your `CLAUDE.md` is over the limit. Which rules is the harness about to silently drop?**

Claude Code warns past **40,000 characters** and may truncate beyond it — quietly disabling
whatever rules fell past the cutoff. The same is true for any agent-context file: `.cursorrules`,
`AGENTS.md`, a raw system prompt. `context-diet` measures where the budget goes, section by
section, then compacts the file under the limit **while proving no rule was lost**.

```bash
bash <(curl -sL https://raw.githubusercontent.com/gaia-research/skill-context-diet/main/install.sh)
```

No pip. No npm. No config file. One Python script (+matplotlib for charts, optional), done.

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

---

## Reproducible methodology

This tool is the packaged output of **Context Diet — Lab 001** (a Gaia Research benchmark). The
full paper-style protocol — metrics, procedure, how to replay on a different context type, and
threats to validity — is in [METHODOLOGY.md](./METHODOLOGY.md).

The inventory and faithfulness scoring are the **reproducible control**: candidate wording varies
run to run, but *which rules must survive* does not.

---

## Requirements

- **Python 3.8+** — the analyzer is pure stdlib.
- **matplotlib** (optional) — only for the before/after charts.

---

## License

MIT — see [LICENSE](./LICENSE). Part of the [Gaia Research](https://github.com/gaia-research) ecosystem.
