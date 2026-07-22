# Context Diet workflow

The user invokes one natural-language command:

```text
/context-diet CLAUDE.md <optional goal>
```

The installed skill manages two phases internally.

## Audit phase (always read-only)

1. Measure the target and initialize `.context-diet/<file>.plan.json`.
2. Inventory directives, invariants, operational facts, literals, procedures,
   prohibitions, dated state, and rationale.
3. Classify each unit as keep, condense, externalize, retire, or delete.
4. Compare no-op, condense, externalize, telegraphic, and hybrid candidates.
5. Report safe, recommended, and aggressive estimates plus the protected floor.
6. Stop without editing and suggest a plain-language follow-up.

## Apply phase (later invocation only)

When a later prompt clearly authorizes mutation, verify that the saved plan still
matches the source hash, create a checkpoint, apply only the authorized tier,
and re-audit the result. Ambiguous prompts remain read-only.

```bash
python3 context_diet.py CLAUDE.md --check-plan
python3 context_diet.py CLAUDE.md --checkpoint --tier recommended
# Agent applies the reviewed rewrite.
python3 context_diet.py CLAUDE.md --complete
```

The 40,000-character default remains a safety indicator. It does not decide
whether a file can benefit from optimization. An 80% request is a stretch goal;
the protected irreducible floor always wins.
