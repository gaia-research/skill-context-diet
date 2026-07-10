---
name: context-diet
description: >-
  Measure and compact an oversized agent-context file (CLAUDE.md, .cursorrules,
  AGENTS.md, a system prompt) so it fits under the harness char limit WITHOUT
  losing any rule. Reports per-section size, runs a bake-off of compaction
  strategies, and scores each on faithfulness (rules retained) before applying
  the winner. Use when a context file is over the limit or bloated. Triggers:
  "CLAUDE.md too big", "over the char limit", "context file too large", "compact
  my agent config", "trim CLAUDE.md", "context diet", "shrink my system prompt",
  "/context-diet".
version: 1.0.0
---

# context-diet — Context Compaction Report

Measure where an agent-context file's character budget goes, section by section,
then compact it under the limit while provably retaining every rule.

## Install

```bash
bash <(curl -sL https://raw.githubusercontent.com/gaia-research/skill-context-diet/main/install.sh)
```

## When to use

- A `CLAUDE.md` / `.cursorrules` / `AGENTS.md` / system prompt is over the harness
  limit (Claude Code warns past **40,000 chars** and may truncate beyond it).
- A context file is bloated and you want to know which sections to cut.
- You want a faithfulness-checked compaction, not a blind delete.

## The two objectives

Compaction is a two-objective problem:

1. **Reduce size** below the limit (target = limit − headroom).
2. **Retain 100% of rules** — an agent-context file is mostly guardrails; any one
   dropped silently lets an agent ship a broken state.

`context-diet` optimizes reduction **subject to** faithfulness, never the reverse.

## How it works

### 1. Measure (`context_diet.py`)

```bash
python3 context_diet.py CLAUDE.md            # human report
python3 context_diet.py CLAUDE.md --json     # machine-readable baseline
python3 context_diet.py .cursorrules --limit 40000
```

Splits on `##` headings, reports per-section chars + approx tokens (chars/4),
total vs `--limit`, and the ranked compaction targets. **Char count is
authoritative** — the limit is defined in characters; tiktoken is not required.

### 2. Bake-off (four strategies)

| Strategy | What it does |
|---|---|
| **Externalize + link** | Move large playbooks to linked files; leave stub = invariant + pointer |
| **Condense in place** | Strip retro/anecdote prose, bullet-ify, keep every rule; no new files |
| **Telegraphic** | Aggressive lexical compression of non-load-bearing prose; keep all literals |
| **Hybrid** | Externalize top-N, condense mid-size, keep enforced sections verbatim |

### 3. Faithfulness scoring (the control)

An exhaustive **rule inventory** is extracted from the original (atomic, testable
directives; each tagged load-bearing if CI-enforced or incident-codified). Each
candidate is then adversarially audited — every rule classified
**present / weakened / missing** against the candidate corpus (its file **plus**
any linked files). **Faithfulness = present / total.**

**Disqualification:** over the hard limit, or any load-bearing rule lost.

### 4. Winner + apply

Winner = qualified candidate with **max faithfulness**, tie-break on larger
reduction. Its rewrite is applied; the analyzer re-run confirms it fits.

## Constraints (must-keep set)

Before compacting, identify the **do-not-touch** sections — CI-enforced or
incident-codified rules that must stay fully inline. For `gaia-skill-tree`'s
CLAUDE.md these are: Redaction Exemptions, Branch Scope allowlists,
Programmatic-First / CLI Pre-Flight, Authorization, Generated Artifacts
(Class P/S), Versioning hard rules. **Re-derive this set for any other file**
(§4 of METHODOLOGY.md).

## Reproducibility

See [METHODOLOGY.md](./METHODOLOGY.md) for the full paper-style protocol and how
to replay the experiment on a different context type. The inventory + scoring are
the reproducible control; candidate wording varies, but which rules must survive
does not.

## Notes

- Externalization ≠ deletion: a rule moved to a linked file is still one hop away.
  The report separates in-context size from total-corpus size so the trade-off is
  explicit.
- LLM compaction is stochastic. For a strict replay, cache the winning candidate
  corpus and re-score it; report faithfulness (stable) + achieved reduction
  (run-specific).
