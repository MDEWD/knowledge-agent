const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const vm = require('node:vm')

const filename = path.resolve(__dirname, '../src/components/deepSessionState.ts')
const source = fs.readFileSync(filename, 'utf8')
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
const moduleRef = { exports: {} }
vm.runInNewContext(output, { module: moduleRef, exports: moduleRef.exports })
const {
  hasDeepSession,
  prepareFollowUpHistory,
  resolveDeepSessionId,
} = moduleRef.exports

assert.equal(hasDeepSession({
  running: false,
  result: '',
  historyLength: 0,
  currentQuestion: '分析年底黄金价格',
  runId: '',
}), true, 'a submitted question must keep the conversation layout active')

assert.equal(hasDeepSession({
  running: false,
  result: '',
  historyLength: 0,
  currentQuestion: '',
  runId: '',
}), false, 'a genuinely new research page must show the initial composer')

assert.equal(
  resolveDeepSessionId('', 'selected-session', 'new-session'),
  'selected-session',
  'a follow-up must reuse the selected session instead of opening a new page',
)

const preserved = prepareFollowUpHistory(
  [],
  '第一轮问题',
  '第一轮完整报告',
)
assert.deepEqual(
  JSON.parse(JSON.stringify(preserved)),
  [{ question: '第一轮问题', answer: '第一轮完整报告' }],
  'the visible completed turn must be retained before starting a follow-up',
)

const alreadyStored = prepareFollowUpHistory(
  [{ question: '第一轮问题', answer: '第一轮完整报告' }],
  '第一轮问题',
  '第一轮完整报告',
)
assert.equal(alreadyStored.length, 1, 'persisted history must not be duplicated')

console.log('deepSessionState regression passed')
