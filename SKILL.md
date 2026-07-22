---
name: context-diet
description: >-
  Audit and optimize agent-context files of any size, including CLAUDE.md,
  AGENTS.md, .cursorrules, and system prompts. Measure recurring context cost,
  preserve operational knowledge, estimate safe through aggressive reduction,
  and compact, externalize, retire, or delete context only with explicit user
  authorization. Use for context cleanup, prompt maintenance, stale rules,
  oversized files, token reduction, or /context-diet.
---

# Context Diet

Reduce recurring context cost without silently discarding operational knowledge.
Treat a harness limit as an optional safety constraint, never as an eligibility gate.

## Workflow

1. Resolve the target file and the user's natural-language goal.
2. Run `python3 context_diet.py <file> --json` for the baseline.
3. Run `python3 context_diet.py <file> --init-plan --goal "<goal>"` to create or
   locate `.context-diet/<file>.plan.json`.
4. Inventory atomic directives, invariants, operational facts, exact literals,
   procedures, prohibitions, dated state, and rationale. Mark incident-codified,
   CI-enforced, authorization, safety, and user-preference items protected.
5. Classify each unit: `keep`, `condense`, `externalize`, `retire`, or `delete`.
6. Compare `no-op`, `condense`, `externalize`, `telegraphic`, and `hybrid`
   candidates. Audit every candidate adversarially against the inventory.
7. Run `python3 context_diet.py <file> --proposal-template` and fill that JSON
   with the audited inventory, actions, exact tier artifacts, protected floor,
   and recommendation. Import it with `--import-proposal <json>`; do not hand-edit
   plan state. Report safe, recommended, and aggressive estimates. An 80%
   request is a stretch goal, not permission to cross the protected floor.

## Authorization boundary

An initial invocation is read-only: save the plan, show estimates and proposed
retire/delete actions, then stop. Never infer destructive authorization from a
request to audit, estimate, review, or "try" a target.

On a later invocation, discover the saved plan automatically. Apply it only when
the user clearly authorizes mutation (for example: "apply", "do it", "remove
these", "accept the recommendation", or "go aggressive"). Before editing:

1. Run `python3 context_diet.py <file> --check-plan`; reject stale plans.
2. Run `python3 context_diet.py <file> --checkpoint --tier <tier>` for recovery
   and to bind authorization to one exact candidate artifact.
3. Apply only the authorized tier and user instructions.
4. Re-measure, validate Markdown and links, and re-audit retained knowledge.
5. Run `python3 context_diet.py <file> --complete` and report the diff, reduction,
   retired context, protected floor, and recovery path.

If authorization is ambiguous, show the recommendation without editing.

## Selection rules

- Require 100% retention of protected items; weakened counts as lost.
- Score inline and total-corpus retention separately. Externalization adds a
  retrieval hop and must not win solely by moving text elsewhere.
- Include `no-op`; recommend change only when it materially improves context.
- Prefer fewer retrieval hops and a smaller diff when faithfulness is equal.
- Retire obsolete context from the active file; do not leave token-consuming
  "deprecated" prose inline. Git or the checkpoint provides history.

Read [METHODOLOGY.md](./METHODOLOGY.md) only for benchmark reproduction, detailed
scoring guidance, or uncertainty about inventory completeness.
