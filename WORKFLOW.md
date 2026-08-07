# Bake-off Workflow (reproducibility artifact)

The four-strategy compaction bake-off is a Claude Code **dynamic workflow**. The exact script
that produced Context Diet — Lab 001 is preserved here so the experiment can be replayed.

## What it does

1. **Inventory** — extract an exhaustive, atomic rule inventory from the original file (the
   scientific control). Each rule tagged `loadBearing` if CI-enforced/incident-codified.
2. **Compact** — run 4 candidate strategies in parallel (externalize, condense, telegraphic,
   hybrid), each producing a proposed rewrite + any linked files.
3. **Verify** — adversarially audit each candidate against the inventory: every rule
   present / weakened / missing (a rule moved to a linked file counts as present).
4. **Score** — disqualify candidates over the hard limit or that drop a load-bearing rule;
   winner = max faithfulness, tie-break on larger reduction.

## How to replay on a different context file

1. Edit the constants at the top of `bakeoff.workflow.js`:
   - `CLAUDE` → absolute path to the target file.
   - `LIMIT` / `TARGET` → the harness char budget and your headroom target.
   - The `CONSTRAINTS` string's "must stay fully inline" list → re-derive the do-not-touch set
     for *your* file (which sections are CI-enforced or incident-codified?).
2. In a Claude Code session in the target repo, invoke the workflow with that script.
3. Feed the returned `winner.claudeMd` + `winner.newFiles` to Phase C (apply), then run
   `context_diet.py <file> --json` for the after-measurement and `make_charts.py` for the charts.

See [METHODOLOGY.md](./METHODOLOGY.md) §4 for the full reproduction protocol and §5 for threats
to validity. The workflow is stochastic in candidate *wording* but deterministic in *which rules
must survive* — cache the winning corpus and re-score it for a strict replay.

> The canonical script is committed alongside this note as `bakeoff.workflow.js` and remains
> unchanged as the Lab 001 provenance artifact.

## Guided-ablation evaluator

`ablation.workflow.js` is a separate product workflow. Unlike the hard-coded Lab 001 bake-off, it
accepts bounded snapshot content, a sealed suite/hash, one parent/candidate pair, 1–5 exact subject
model IDs, one exact designer/judge ID, and 1–5 repetitions.

For each stable model/repetition work ID it:

1. explicitly routes a fresh parent simulation to the requested exact subject model;
2. for trials, routes the one-unit candidate through the same task prompts;
3. keeps sealed rubrics out of subject prompts;
4. asks the exact disclosed judge model to classify each response `pass`, `fail`, or
   `inconclusive`;
5. preserves unavailable routes, null calls, missing cases, and judge failures as missing coverage;
6. returns baseline/trial evidence bound to suite, parent, candidate, trial, model, judge, and
   repetition values for `context_diet.py ablate record-evidence`.

Every `agent()` call has a stable label. Work is batched at concurrency two, and user inputs are
bounded to at most five models, five repetitions, and ten cases. Explicit route failures are caught
and reported; there is no fallback to the session model.

The workflow sends snapshot and evaluation content to the selected providers. Obtain disclosure
consent and show expected call volume before invocation. It is a controlled prompt simulation, not
a faithful reproduction of every host's production context-loading order or tools. Its output
supports only experiment-scoped wording such as “no regression observed for this exact route and
sealed suite.” See [ABLATION.md](./ABLATION.md).
