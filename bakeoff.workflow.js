// Portable Context Diet bake-off. This workflow proposes; it never mutates.
export const meta = {
  name: 'context-diet-bakeoff',
  description: 'Audit any context file and compare no-op plus four optimization strategies',
  phases: [
    { title: 'Inventory', detail: 'extract protected operational knowledge' },
    { title: 'Compact', detail: 'generate candidates plus no-op control' },
    { title: 'Verify', detail: 'adversarially score retention and retrieval cost' },
    { title: 'Recommend', detail: 'return a reviewed plan without mutation' },
  ],
}

const FILE = process.env.CONTEXT_DIET_FILE || 'CLAUDE.md'
const rawLimit = Number(process.env.CONTEXT_DIET_LIMIT || 0)
const LIMIT = Number.isFinite(rawLimit) && rawLimit > 0 ? rawLimit : null
const GOAL = process.env.CONTEXT_DIET_GOAL || 'Optimize recurring context cost'

phase('Inventory')
const inventory = await agent(
  `Read ${FILE} fully. Return its exact character count and an exhaustive atomic inventory of
directives, invariants, operational facts, exact literals, procedures, prohibitions, dated state,
and rationale. Mark protected items: CI-enforced, incident-codified, safety, authorization,
explicit user preferences, or anything unsafe to weaken. Estimate the irreducible inline floor.
User goal: ${GOAL}`,
  { phase: 'Inventory', effort: 'high', schema: {
    type: 'object', required: ['originalChars', 'protectedFloorChars', 'items'], properties: {
      originalChars: { type: 'integer' }, protectedFloorChars: { type: 'integer' },
      items: { type: 'array', items: { type: 'object', required: ['id', 'kind', 'text', 'protected'], properties: {
        id: { type: 'string' }, kind: { type: 'string' }, text: { type: 'string' },
        protected: { type: 'boolean' },
      }}},
    },
  }}
)

const strategies = [
  ['condense', 'Condense in place', 'Remove padding and repetition; keep knowledge inline.'],
  ['externalize', 'Externalize', 'Move low-frequency detail one hop away; keep routing stubs.'],
  ['telegraphic', 'Telegraphic', 'Use terse wording while preserving protected nuance and literals.'],
  ['hybrid', 'Hybrid', 'Condense common material, externalize detail, and propose obsolete items for retirement.'],
]
const itemList = inventory.items.map(item =>
  `[${item.id}]${item.protected ? ' PROTECTED' : ''} (${item.kind}) ${item.text}`).join('\n')

phase('Compact')
const generated = await parallel(strategies.map(([key, title, instructions]) => () => agent(
  `Propose a complete rewrite of ${FILE}; do not edit files. Strategy: ${instructions}
Goal: ${GOAL}. Hard limit: ${LIMIT || 'none'}. Protected floor: ${inventory.protectedFloorChars}.
Inventory:\n${itemList}
Return the primary file, linked files, and retire/delete proposals separately. Never remove a
protected item to hit a percentage.`,
  { phase: 'Compact', effort: 'high', schema: {
    type: 'object', required: ['primary', 'linkedFiles', 'retireProposals', 'approach'], properties: {
      primary: { type: 'string' }, approach: { type: 'string' },
      retireProposals: { type: 'array', items: { type: 'string' } },
      linkedFiles: { type: 'array', items: { type: 'object', required: ['path', 'content'], properties: {
        path: { type: 'string' }, content: { type: 'string' },
      }}},
    },
  }}
).then(out => ({ key, title, out }))))

const candidates = [
  { key: 'noop', title: 'No change', out: { primary: null, linkedFiles: [], retireProposals: [], approach: 'No change.' } },
  ...generated,
]

phase('Verify')
const verified = await parallel(candidates.map(candidate => () => agent(
  `Adversarially audit the ${candidate.title} candidate. Default to weakened or missing when an
inventory item is not clearly recoverable. Score inline and total-corpus retention separately;
count retrieval hops and diff complexity. For no-op, read ${FILE} as the candidate.
INVENTORY:\n${itemList}
CANDIDATE:\n${candidate.key === 'noop' ? `Original file at ${FILE}` : candidate.out.primary}
${candidate.out.linkedFiles.map(file => `\nLINKED ${file.path}:\n${file.content}`).join('\n')}`,
  { phase: 'Verify', effort: 'high', schema: {
    type: 'object', required: ['weakened', 'missing', 'protectedLoss', 'inlineRetention',
      'corpusRetention', 'retrievalHops', 'diffComplexity'], properties: {
      weakened: { type: 'array', items: { type: 'string' } },
      missing: { type: 'array', items: { type: 'string' } },
      protectedLoss: { type: 'array', items: { type: 'string' } },
      inlineRetention: { type: 'number' }, corpusRetention: { type: 'number' },
      retrievalHops: { type: 'integer' }, diffComplexity: { type: 'number' },
    },
  }}
).then(audit => {
  const chars = candidate.key === 'noop' ? inventory.originalChars : candidate.out.primary.length
  return { ...candidate, ...audit, chars,
    reduction: inventory.originalChars - chars,
    reductionPct: +(((inventory.originalChars - chars) / inventory.originalChars) * 100).toFixed(1),
    qualified: audit.protectedLoss.length === 0 && (!LIMIT || chars <= LIMIT) }
})))

phase('Recommend')
const qualified = verified.filter(result => result.qualified)
qualified.sort((a, b) =>
  b.corpusRetention - a.corpusRetention || b.inlineRetention - a.inlineRetention ||
  a.retrievalHops - b.retrievalHops || a.diffComplexity - b.diffComplexity ||
  b.reduction - a.reduction)
const winner = qualified[0] || verified.find(result => result.key === 'noop')

return {
  file: FILE, goal: GOAL, limit: LIMIT,
  inventory: { total: inventory.items.length, protectedFloorChars: inventory.protectedFloorChars },
  comparison: verified.map(({ out, ...summary }) => summary),
  recommendation: winner ? { key: winner.key, title: winner.title, chars: winner.chars,
    reductionPct: winner.reductionPct, retireProposals: winner.out.retireProposals } : null,
  proposedArtifact: winner && winner.key !== 'noop' ? winner.out : null,
  applied: false,
}
