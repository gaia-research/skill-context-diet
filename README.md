# context-diet

**Your agent reads this file every turn. How much of it still earns that cost?**

`context-diet` audits and optimizes `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, and
other agent-context files of any size. It measures recurring context cost,
preserves operational knowledge, and estimates what can be condensed,
externalized, retired, or deleted before changing anything.

```bash
bash <(curl -sL https://raw.githubusercontent.com/gaia-research/skill-context-diet/main/install.sh)
```

No pip, npm, API key, or configuration required. Python 3.8+ is enough.

## One conversational interface

```text
/context-diet CLAUDE.md
/context-diet CLAUDE.md try to get near 80%
/context-diet CLAUDE.md remove the stale branch history
/context-diet CLAUDE.md looks good, apply the recommendation
```

The first invocation is read-only. It reports safe, recommended, and aggressive
reduction estimates and saves a source-hashed plan. A later invocation applies
changes only when the user clearly authorizes mutation. Stale plans are rejected,
and every apply starts with a recoverable checkpoint.

## What it protects

Context is inventoried as directives, invariants, operational facts, exact
literals, procedures, prohibitions, dated state, and rationale. Each unit is
classified as:

| Action | Meaning |
|---|---|
| Keep | Frequently needed or protected inline context |
| Condense | Useful content with removable prose |
| Externalize | Useful, low-frequency detail loaded on demand |
| Retire | Superseded or expired context removed from the active file |
| Delete | Duplicate, contradicted, or cheaply discoverable material |

Protected context—CI rules, safety and authorization boundaries,
incident-codified invariants, exact literals, and explicit user preferences—is
never sacrificed to meet a percentage. An 80% request is a stretch goal, not a
quota.

## Selection

The skill compares five candidates: no-op, condense in place, externalize,
telegraphic, and hybrid. It scores protected retention, inline retention,
total-corpus retention, retrieval hops, new files, diff complexity, and size.
Externalization cannot win merely by moving text elsewhere, and no-op wins when
no candidate offers a material improvement.

## Direct analyzer usage

```bash
python3 context_diet.py CLAUDE.md
python3 context_diet.py CLAUDE.md --json
python3 context_diet.py CLAUDE.md --limit 40000
python3 context_diet.py CLAUDE.md --init-plan --goal "Get near 80% if defensible"
python3 context_diet.py CLAUDE.md --proposal-template > proposal.json
python3 context_diet.py CLAUDE.md --import-proposal proposal.json
python3 context_diet.py CLAUDE.md --check-plan
python3 context_diet.py CLAUDE.md --leaderboard-preview \
  --before-url https://github.com/owner/repo/blob/BEFORE_SHA/CLAUDE.md \
  --after-url https://github.com/owner/repo/blob/AFTER_SHA/CLAUDE.md
# Only after the user approves the exact preview:
python3 context_diet.py CLAUDE.md --submit-leaderboard --confirm \
  --before-url https://github.com/owner/repo/blob/BEFORE_SHA/CLAUDE.md \
  --after-url https://github.com/owner/repo/blob/AFTER_SHA/CLAUDE.md
```

Leaderboard submission is opt-in per run and ranked only with public GitHub
before/after evidence. The server fetches both revisions and calculates the
metrics; it never accepts slider or client-supplied scores. Private diets remain
local and unranked.

Plans live at `.context-diet/<file>.plan.json`; add `.context-diet/` to the target
repository's ignore file if desired. See [WORKFLOW.md](./WORKFLOW.md) for the
state transition and [METHODOLOGY.md](./METHODOLOGY.md) for benchmark details.

## Updating

Installed copies do not update automatically. Re-run the installer and approve
replacement, or use its non-interactive update mode:

```bash
bash <(curl -sL https://raw.githubusercontent.com/gaia-research/skill-context-diet/main/install.sh) --update
```

When several skill roots exist, select one interactively or set
`CONTEXT_DIET_SKILLS_DIR=.agents/skills` for unattended updates.

## License

MIT. Part of the [Gaia Research](https://github.com/gaia-research) ecosystem.
