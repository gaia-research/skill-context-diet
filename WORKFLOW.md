# Audit → Apply Workflow (reproducibility artifact)

The compaction bake-off is a Claude Code **dynamic workflow**, and the exact script that produced
Context Diet — Lab 001 is preserved here so the experiment can be replayed. What changed in v1.1:
the workflow no longer edits anything on the first pass. It splits into a read-only **audit** and
a later, explicitly authorized **apply** — so the same measurement can be reviewed before a single
character moves.

You drive the whole thing with one natural-language command:

```text
/context-diet CLAUDE.md <optional goal>
```

## Audit phase — always read-only

1. **Measure** — `python3 context_diet.py <file> --json` for the baseline, then
   `--init-plan --goal "<goal>"` to create or locate `.context-diet/<file>.plan.json`.
2. **Inventory** — extract an exhaustive, atomic inventory: directives, invariants, operational
   facts, exact literals, procedures, prohibitions, dated state, rationale. Tag the protected ones
   (CI-enforced, incident-codified, safety, authorization, explicit user preference).
3. **Classify** — every unit becomes `keep`, `condense`, `externalize`, `retire`, or `delete`.
4. **Bake off** — run 5 candidate strategies (no-op, externalize, condense, telegraphic, hybrid)
   in parallel, each a *proposed* rewrite, and adversarially audit each against the inventory
   (a rule moved to a linked file counts as present).
5. **Report** — safe / recommended / aggressive estimates plus the protected floor. Then **stop**,
   and suggest a plain-language follow-up. Nothing on disk is touched.

## Apply phase — later invocation only

When a later prompt *clearly* authorizes mutation, and not before:

```bash
python3 context_diet.py CLAUDE.md --check-plan          # reject a stale plan (source hash moved)
python3 context_diet.py CLAUDE.md --checkpoint --tier recommended   # recoverable, binds one artifact
# Agent applies the reviewed rewrite for that tier only.
python3 context_diet.py CLAUDE.md --complete            # re-measure, re-audit, report the diff
```

Ambiguous prompts stay read-only. The 40,000-character default is a safety indicator, not an
eligibility gate — an 80% request is a stretch goal, and the protected irreducible floor always
wins.

## How to replay on a different context file

1. Edit the constants at the top of `bakeoff.workflow.js`:
   - `CLAUDE` → absolute path to the target file.
   - `LIMIT` / `TARGET` → the harness char budget and your headroom target.
   - The `CONSTRAINTS` string's protected-floor list → re-derive the do-not-touch set for *your*
     file (which sections are CI-enforced or incident-codified?).
2. In a Claude Code session in the target repo, invoke the workflow with that script.
3. Feed the winning candidate through the apply phase above, then run `context_diet.py <file>
   --json` for the after-measurement and `make_charts.py` for the charts.

See [METHODOLOGY.md](./METHODOLOGY.md) §4 for the full reproduction protocol and §5 for threats
to validity. The workflow is stochastic in candidate *wording* but deterministic in *which rules
must survive* — cache the winning corpus and re-score it for a strict replay.

> The canonical script is committed alongside this note as `bakeoff.workflow.js`.
