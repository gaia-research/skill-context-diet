// Portable, rule-preserving Context Diet bake-off for any context file.
// This workflow proposes candidates only; it never mutates the target.
export const meta = {
  name: 'context-diet-any-size-bakeoff',
  description: 'Compare a no-op and four rule-preserving optimizations for any context file',
  phases: [
    { title: 'Inventory', detail: 'extract the complete context inventory' },
    { title: 'Compact', detail: 'generate candidate corpora' },
    { title: 'Verify', detail: 'adversarially check every inventoried item' },
    { title: 'Recommend', detail: 'select a safe candidate or the no-op control' },
  ],
}

const input = args && typeof args === 'object' ? args : {}
const FILE = typeof input.file === 'string' && input.file ? input.file : 'CLAUDE.md'
const parsedLimit = Number(input.limit || 0)
const LIMIT = Number.isFinite(parsedLimit) && parsedLimit > 0 ? parsedLimit : null
const GOAL = typeof input.goal === 'string' && input.goal
  ? input.goal
  : 'Reduce recurring context cost without losing any inventoried knowledge'
const MIN_REDUCTION_PCT = 1

function countLost(audit) {
  return new Set([...(audit.missing || []), ...(audit.weakened || [])])
}

function asPercent(value, fallback = 0) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

phase('Inventory')
const inventory = await agent(
  `Read ${FILE} fully. Return its exact character count and an exhaustive atomic inventory of
all directives, invariants, operational facts, exact literals, procedures, prohibitions, dated state,
and rationale. Each item needs a stable id, kind, text, and protected boolean. Mark CI-enforced,
incident-codified, safety, authorization, explicit user-preference, and routing items protected.
Estimate the irreducible protected inline floor. This is the normal rule-preserving compaction path:
intentional rule loss belongs to guided ablation instead. User goal: ${GOAL}`,
  {
    label: 'inventory',
    phase: 'Inventory',
    effort: 'high',
    schema: {
      type: 'object',
      required: ['originalChars', 'protectedFloorChars', 'items'],
      properties: {
        originalChars: { type: 'integer' },
        protectedFloorChars: { type: 'integer' },
        items: {
          type: 'array',
          items: {
            type: 'object',
            required: ['id', 'kind', 'text', 'protected'],
            properties: {
              id: { type: 'string' },
              kind: { type: 'string' },
              text: { type: 'string' },
              protected: { type: 'boolean' },
            },
          },
        },
      },
    },
  },
)

if (!inventory) {
  log('Inventory unavailable; no recommendation produced.')
  return { file: FILE, goal: GOAL, limit: LIMIT, inventory: null, comparison: [], winnerKey: null, winner: null }
}

const itemList = inventory.items.map(item =>
  `[${item.id}]${item.protected ? ' PROTECTED' : ''} (${item.kind}) ${item.text}`,
).join('\n')
const protectedIds = new Set(inventory.items.filter(item => item.protected).map(item => item.id))
const totalItems = inventory.items.length

const strategies = [
  ['condense', 'Condense in place', 'Remove padding and repetition while keeping all knowledge inline.'],
  ['externalize', 'Externalize and link', 'Move low-frequency detail one hop away and leave a concise routing stub.'],
  ['telegraphic', 'Telegraphic', 'Use terse wording while preserving every rule and exact literal.'],
  ['hybrid', 'Hybrid', 'Condense common material and externalize detail, without retiring any item.'],
]

phase('Compact')
const generated = await parallel(strategies.map(([key, title, instructions]) => () => agent(
  `Propose a complete rewrite of ${FILE}; do not edit files. Strategy: ${instructions}
Goal: ${GOAL}. ${LIMIT ? `Hard limit: ${LIMIT}.` : 'No hard limit was supplied; optimize recurring cost.'}
Protected floor: ${inventory.protectedFloorChars} characters.
INVENTORY:\n${itemList}
Every inventoried item must remain recoverable from the primary file plus linked files. Do not
retire or delete a rule; intentional rule loss must use guided ablation. Return the primary file,
linked files, and a short approach.`,
  {
    label: `compact:${key}`,
    phase: 'Compact',
    effort: 'high',
    schema: {
      type: 'object',
      required: ['primary', 'linkedFiles', 'approach'],
      properties: {
        primary: { type: 'string' },
        approach: { type: 'string' },
        linkedFiles: {
          type: 'array',
          items: {
            type: 'object',
            required: ['path', 'content'],
            properties: { path: { type: 'string' }, content: { type: 'string' } },
          },
        },
      },
    },
  },
).then(out => out ? { key, title, out } : null)))

const candidates = [
  {
    key: 'noop',
    title: 'No change',
    out: { primary: null, linkedFiles: [], approach: 'Retain the original corpus.' },
  },
  ...generated.filter(Boolean),
]

phase('Verify')
const audited = await parallel(candidates.map(candidate => () => {
  if (candidate.key === 'noop') return Promise.resolve({
    candidate,
    missing: [],
    weakened: [],
    protectedLoss: [],
    inlineRetention: 100,
    corpusRetention: 100,
    retrievalHops: 0,
    diffComplexity: 0,
    chars: inventory.originalChars,
  })
  return agent(
    `Adversarially audit the ${candidate.title} candidate. Default to weakened or missing when an
inventory item is not clearly recoverable. A linked file counts only when the primary file gives a
resolvable one-hop route. Report missing and weakened item ids separately, plus protectedLoss for
protected items. Score inline and total-corpus retention from 0 to 100. Count retrieval hops and
diff complexity.\nINVENTORY:\n${itemList}\nPRIMARY CANDIDATE:\n${candidate.out.primary}
${candidate.out.linkedFiles.map(file => `\nLINKED ${file.path}:\n${file.content}`).join('\n')}`,
    {
      label: `verify:${candidate.key}`,
      phase: 'Verify',
      effort: 'high',
      schema: {
        type: 'object',
        required: ['missing', 'weakened', 'protectedLoss', 'inlineRetention',
          'corpusRetention', 'retrievalHops', 'diffComplexity'],
        properties: {
          missing: { type: 'array', items: { type: 'string' } },
          weakened: { type: 'array', items: { type: 'string' } },
          protectedLoss: { type: 'array', items: { type: 'string' } },
          inlineRetention: { type: 'number' },
          corpusRetention: { type: 'number' },
          retrievalHops: { type: 'integer' },
          diffComplexity: { type: 'number' },
        },
      },
    },
  ).then(audit => audit ? {
    candidate,
    ...audit,
    chars: candidate.out.primary.length,
  } : null)
}))

const results = audited.filter(Boolean).map(result => {
  const lost = countLost(result)
  const protectedLoss = [...new Set([
    ...(result.protectedLoss || []),
    ...[...lost].filter(id => protectedIds.has(id)),
  ])]
  const underLimit = !LIMIT || result.chars <= LIMIT
  const qualified = lost.size === 0 && protectedLoss.length === 0 && underLimit
  const reduction = inventory.originalChars - result.chars
  return {
    key: result.candidate.key,
    title: result.candidate.title,
    approach: result.candidate.out.approach,
    charCount: result.chars,
    reduction,
    reductionPct: inventory.originalChars
      ? +((reduction / inventory.originalChars) * 100).toFixed(1)
      : 0,
    underLimit,
    underTarget: underLimit,
    faithfulness: totalItems ? +(((totalItems - lost.size) / totalItems) * 100).toFixed(1) : 100,
    inlineRetention: asPercent(result.inlineRetention),
    corpusRetention: asPercent(result.corpusRetention),
    retrievalHops: result.retrievalHops,
    diffComplexity: asPercent(result.diffComplexity),
    missing: [...lost].filter(id => (result.missing || []).includes(id)),
    weakened: [...lost].filter(id => (result.weakened || []).includes(id)),
    protectedLoss,
    qualified,
    linkedFiles: result.candidate.out.linkedFiles,
    primary: result.candidate.out.primary,
  }
})

phase('Recommend')
const noOp = results.find(result => result.key === 'noop')
const safeChanges = results
  .filter(result => result.key !== 'noop' && result.qualified &&
    result.reductionPct >= MIN_REDUCTION_PCT)
  .sort((a, b) =>
    b.reduction - a.reduction ||
    a.retrievalHops - b.retrievalHops ||
    a.diffComplexity - b.diffComplexity)
const winner = safeChanges[0] || noOp || results[0] || null

for (const result of results) {
  log(`${result.title}: ${result.charCount} chars (-${result.reductionPct}%), ` +
    `faithfulness ${result.faithfulness}%, ${result.qualified ? 'QUALIFIED' : 'DISQUALIFIED'}`)
}
if (winner) log(`RECOMMENDATION → ${winner.title} @ ${winner.charCount} chars`)

return {
  file: FILE,
  goal: GOAL,
  limit: LIMIT,
  inventory: {
    total: totalItems,
    protected: protectedIds.size,
    protectedFloorChars: inventory.protectedFloorChars,
  },
  originalChars: inventory.originalChars,
  comparison: results.map(({ primary, linkedFiles, ...summary }) => summary),
  winnerKey: winner ? winner.key : null,
  winner: winner ? {
    key: winner.key,
    title: winner.title,
    charCount: winner.charCount,
    faithfulness: winner.faithfulness,
    reductionPct: winner.reductionPct,
    claudeMd: winner.primary,
    newFiles: winner.linkedFiles,
  } : null,
}
