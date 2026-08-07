export const meta = {
  name: 'context-diet-ablation-eval',
  description: 'Run bounded, exact-model context ablation simulations and return importable evidence',
  phases: [
    { title: 'Prepare', detail: 'validate sealed inputs and exact model routes' },
    { title: 'Evaluate', detail: 'run and conservatively judge current/candidate simulations' },
  ],
}

phase('Prepare')

function requireString(value, name) {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${name} must be a non-empty string`)
  return value
}

function exactModel(value, name) {
  const model = requireString(value, name)
  if (!model.includes('/') || /\s/.test(model)) throw new Error(`${name} must be an exact provider/model id`)
  return model
}

const operation = args.operation
if (operation !== 'baseline' && operation !== 'trial') throw new Error('operation must be baseline or trial')
const parentContext = requireString(args.parentContext, 'parentContext')
const candidateContext = operation === 'trial' ? requireString(args.candidateContext, 'candidateContext') : null
const parentSha256 = requireString(args.parentSha256, 'parentSha256')
const candidateSha256 = operation === 'trial' ? requireString(args.candidateSha256, 'candidateSha256') : null
const suiteSha256 = requireString(args.suiteSha256, 'suiteSha256')
const trialId = operation === 'trial' ? requireString(args.trialId, 'trialId') : null
const judgeModel = exactModel(args.judgeModel, 'judgeModel')
const repetitions = Number(args.repetitions)
if (!Number.isInteger(repetitions) || repetitions < 1 || repetitions > 10) throw new Error('repetitions must be an integer from 1 to 10')
if (!Array.isArray(args.models) || args.models.length < 1 || args.models.length > 5) throw new Error('models must contain 1-5 exact ids')
const models = args.models.map((value, index) => exactModel(value, `models[${index}]`))
if (new Set(models).size !== models.length) throw new Error('models must be unique')
if (!Array.isArray(args.cases) || args.cases.length < 3 || args.cases.length > 7) throw new Error('cases must contain 3-7 sealed cases')
const cases = args.cases.map((item, index) => {
  if (!item || typeof item !== 'object') throw new Error(`cases[${index}] must be an object`)
  return {
    id: requireString(item.id, `cases[${index}].id`),
    prompt: requireString(item.prompt, `cases[${index}].prompt`),
    rubric: requireString(item.rubric, `cases[${index}].rubric`),
    critical: item.critical !== false,
  }
})
if (new Set(cases.map(item => item.id)).size !== cases.length) throw new Error('case ids must be unique')

const SUBJECT_SCHEMA = {
  type: 'object',
  required: ['outputs'],
  properties: {
    outputs: {
      type: 'array',
      items: {
        type: 'object',
        required: ['caseId', 'response'],
        properties: {
          caseId: { type: 'string' },
          response: { type: 'string' },
        },
      },
    },
  },
}

const JUDGE_SCHEMA = {
  type: 'object',
  required: ['cases'],
  properties: {
    cases: {
      type: 'array',
      items: {
        type: 'object',
        required: ['caseId', 'parentStatus', 'candidateStatus', 'reason'],
        properties: {
          caseId: { type: 'string' },
          parentStatus: { type: 'string', enum: ['pass', 'fail', 'inconclusive'] },
          candidateStatus: { type: 'string', enum: ['pass', 'fail', 'inconclusive'] },
          reason: { type: 'string' },
        },
      },
    },
  },
}

function subjectPrompt(context, selectedCases) {
  const tasks = selectedCases.map(item => `[${item.id}] ${item.prompt}`).join('\n\n')
  return `Use only the context snapshot below as the repository-specific instruction source. Treat each task as an independent simulation. Do not evaluate the context or discuss whether instructions were removed. Return one response per case id.\n\n<CONTEXT_SNAPSHOT>\n${context}\n</CONTEXT_SNAPSHOT>\n\n<TASKS>\n${tasks}\n</TASKS>`
}

function exactSubjectMap(result) {
  if (!result || !Array.isArray(result.outputs) || result.outputs.length !== cases.length) return null
  const mapped = {}
  const expected = new Set(cases.map(item => item.id))
  for (const item of result.outputs) {
    if (!item || typeof item.caseId !== 'string' || typeof item.response !== 'string' ||
        !expected.has(item.caseId) || Object.prototype.hasOwnProperty.call(mapped, item.caseId)) return null
    mapped[item.caseId] = item.response
  }
  return Object.keys(mapped).length === cases.length ? mapped : null
}

function exactJudgment(result) {
  if (!result || !Array.isArray(result.cases) || result.cases.length !== cases.length) return null
  const expected = new Set(cases.map(item => item.id))
  const seen = new Set()
  for (const item of result.cases) {
    if (!item || !expected.has(item.caseId) || seen.has(item.caseId)) return null
    seen.add(item.caseId)
  }
  return seen.size === cases.length ? result : null
}

async function runWork(work) {
  let parent = null
  let candidate = null
  let subjectError = null
  try {
    parent = await agent(subjectPrompt(parentContext, cases), {
      label: `parent:${work.modelIndex}:${work.repetition}`,
      model: work.model,
      schema: SUBJECT_SCHEMA,
    })
  } catch (error) {
    subjectError = `parent unavailable: ${String(error)}`
  }
  if (operation === 'trial') {
    try {
      candidate = await agent(subjectPrompt(candidateContext, cases), {
        label: `candidate:${work.modelIndex}:${work.repetition}`,
        model: work.model,
        schema: SUBJECT_SCHEMA,
      })
    } catch (error) {
      subjectError = `${subjectError ? `${subjectError}; ` : ''}candidate unavailable: ${String(error)}`
    }
  } else {
    candidate = parent
  }
  if (!parent || !candidate) {
    return { id: work.id, model: work.model, repetition: work.repetition, status: 'missing_subject_coverage', error: subjectError, judgment: null }
  }

  const parentOutputs = exactSubjectMap(parent)
  const candidateOutputs = exactSubjectMap(candidate)
  if (!parentOutputs || !candidateOutputs) {
    return {
      id: work.id,
      model: work.model,
      repetition: work.repetition,
      status: 'missing_subject_coverage',
      error: 'subject output omitted, duplicated, or added a sealed case id',
      judgment: null,
    }
  }
  const judgeCases = cases.map(item => ({
    id: item.id,
    rubric: item.rubric,
    parentResponse: parentOutputs[item.id] || null,
    candidateResponse: candidateOutputs[item.id] || null,
  }))
  let judgment = null
  let judgeError = null
  try {
    const rawJudgment = await agent(
      `Act as a conservative blind semantic judge. Apply each sealed rubric independently to the two labeled responses. Missing, malformed, or ambiguous coverage is inconclusive, never pass. Do not infer safety beyond this suite.\n\n${JSON.stringify(judgeCases)}`,
      {
        label: `judge:${work.modelIndex}:${work.repetition}`,
        model: judgeModel,
        schema: JUDGE_SCHEMA,
      }
    )
    judgment = exactJudgment(rawJudgment)
    if (!judgment) judgeError = 'judge output omitted, duplicated, or added a sealed case id'
  } catch (error) {
    judgeError = `judge unavailable: ${String(error)}`
  }
  return {
    id: work.id,
    model: work.model,
    repetition: work.repetition,
    status: judgment ? 'complete' : 'missing_judge_coverage',
    error: judgeError,
    judgment,
  }
}

async function runInBatches(items, size) {
  const results = []
  for (let offset = 0; offset < items.length; offset += size) {
    const batch = items.slice(offset, offset + size)
    const values = await parallel(batch.map(item => () => runWork(item)))
    results.push(...values)
  }
  return results
}

const work = []
for (let modelIndex = 0; modelIndex < models.length; modelIndex += 1) {
  for (let repetition = 0; repetition < repetitions; repetition += 1) {
    work.push({
      id: `model-${modelIndex}:rep-${repetition}`,
      model: models[modelIndex],
      modelIndex,
      repetition,
    })
  }
}

phase('Evaluate')
const ledger = await runInBatches(work, 2)
const evidence = models.map(model => {
  const perModel = ledger.filter(item => item && item.model === model)
  const perCase = cases.map(testCase => {
    const parentRuns = []
    const runs = []
    for (let repetition = 0; repetition < repetitions; repetition += 1) {
      const item = perModel.find(entry => entry.repetition === repetition)
      const judged = item && item.judgment && Array.isArray(item.judgment.cases)
        ? item.judgment.cases.find(entry => entry.caseId === testCase.id)
        : null
      parentRuns.push(judged ? judged.parentStatus : 'inconclusive')
      runs.push(judged ? (operation === 'trial' ? judged.candidateStatus : judged.parentStatus) : 'inconclusive')
    }
    return operation === 'trial'
      ? { caseId: testCase.id, parentRuns, runs }
      : { caseId: testCase.id, runs }
  })
  return {
    schemaVersion: 1,
    kind: operation,
    modelId: model,
    actualModelId: model,
    judgeModelId: judgeModel,
    suiteSha256,
    parentSha256,
    candidateSha256: operation === 'trial' ? candidateSha256 : null,
    trialId,
    repetitions,
    freshContext: true,
    cases: perCase,
  }
})

const missing = ledger.filter(item => !item || item.status !== 'complete').map(item => item ? ({ id: item.id, model: item.model, status: item.status, error: item.error }) : ({ status: 'missing_work_item' }))
log(`Ablation evaluation: ${ledger.length - missing.length}/${ledger.length} work items complete; ${missing.length} incomplete`)
return {
  operation,
  suiteSha256,
  parentSha256,
  candidateSha256,
  trialId,
  requestedModels: models,
  judgeModel,
  repetitions,
  evidence,
  coverage: {
    intendedWorkIds: work.map(item => item.id),
    completed: ledger.length - missing.length,
    missing,
  },
  limitation: 'Controlled prompt simulations are scoped evidence, not proof of production harness behavior or other model versions.',
}
