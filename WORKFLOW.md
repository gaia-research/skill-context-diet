# Bake-off Workflows

The repository keeps the original `bakeoff.workflow.js` unchanged as the Context Diet — Lab 001
provenance artifact. For normal use, `bakeoff-any-size.workflow.js` is the generalized Claude Code
dynamic workflow: it accepts any context file, treats the limit as optional, and includes a no-op
control so a rewrite is recommended only when it materially reduces inline size.

## Any-size workflow

Pass workflow arguments as `{ file, limit, goal }`; `file` defaults to `CLAUDE.md`, and `limit` is
optional. The workflow:

1. **Inventories** every directive, invariant, operational fact, exact literal, procedure,
   prohibition, dated state, and rationale.
2. **Compacts** using condense, externalize, telegraphic, and hybrid strategies, plus a no-op.
3. **Verifies** every inventoried item adversarially. A linked item counts only through a resolvable
   one-hop route; weakened or missing items disqualify a candidate.
4. **Recommends** the largest safe reduction meeting the supplied limit, or the no-op when no
   candidate achieves at least a 1% reduction while retaining the complete inventory.

The workflow only returns proposed artifacts. The host presents the candidate and diff, then uses
its normal review-gated file-edit flow. Intentional rule loss belongs to the separate guided-ablation
path below. After applying a candidate, run `context_diet.py <file> --json` and validate any linked
files before committing.

## Replaying Lab 001

To reproduce the original experiment, use the frozen `bakeoff.workflow.js` and its documented
parameters. It remains tied to the original `CLAUDE.md`, 40,000-character limit, and Lab 001
protected sections by design. Use the any-size workflow for a different repository or context type.

See [METHODOLOGY.md](./METHODOLOGY.md) §4 for the reproduction protocol and §5 for threats to
validity. Both workflows are stochastic in candidate wording; retain the returned corpus and
re-score it when strict replay is required.

> The canonical Lab 001 script is `bakeoff.workflow.js`; the generalized script is
> `bakeoff-any-size.workflow.js`.

## Guided-ablation evaluator

`ablation.workflow.js` is a separate product workflow. Unlike the hard-coded Lab 001 bake-off, it
accepts bounded snapshot content, a sealed suite/hash, one parent/candidate pair, 1–5 exact subject
model IDs, one exact designer/judge ID, 3–7 sealed cases, and 1–10 repetitions.

For each stable model/repetition work ID it:

1. explicitly routes a fresh parent simulation to the requested exact subject model;
2. for trials, routes the bounded-unit candidate through the same task prompts;
3. keeps sealed rubrics out of subject prompts;
4. asks the exact disclosed judge model to classify each response `pass`, `fail`, or
   `inconclusive`;
5. preserves unavailable routes, null calls, missing cases, and judge failures as missing coverage;
6. returns baseline/trial evidence bound to suite, parent, candidate, trial, model, judge, and
   repetition values for `context_diet.py ablate record-evidence`.

Every `agent()` call has a stable label. Work is batched at concurrency two, and user inputs are
bounded to at most five models, ten repetitions, and seven cases. Explicit route failures are caught
and reported; there is no fallback to the session model.

The workflow sends snapshot and evaluation content to the selected providers. Obtain disclosure
consent and show expected call volume before invocation. It is a controlled prompt simulation, not
a faithful reproduction of every host's production context-loading order or tools. Its output
supports only experiment-scoped wording such as “no regression observed for this exact route and
sealed suite.” See [ABLATION.md](./ABLATION.md).
