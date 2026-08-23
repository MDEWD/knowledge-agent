const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const ts = require('typescript')
const vm = require('node:vm')

function loadModule() {
  const filename = path.resolve(__dirname, '../src/tabPersistence.ts')
  const source = fs.readFileSync(filename, 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText
  const moduleRef = { exports: {} }
  vm.runInNewContext(output, { module: moduleRef, exports: moduleRef.exports })
  return moduleRef.exports
}

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
  }
}

test('the active workspace survives a browser refresh', () => {
  const { ACTIVE_TAB_STORAGE_KEY, readActiveTab, saveActiveTab } = loadModule()
  const storage = memoryStorage()
  saveActiveTab('deep', storage)
  assert.equal(storage.getItem(ACTIVE_TAB_STORAGE_KEY), 'deep')
  assert.equal(readActiveTab(storage), 'deep')
})

test('invalid stored tabs fall back safely', () => {
  const { ACTIVE_TAB_STORAGE_KEY, readActiveTab } = loadModule()
  assert.equal(readActiveTab(memoryStorage({ [ACTIVE_TAB_STORAGE_KEY]: 'removed-page' })), 'add')
})

test('admin workspace is restored only for administrators', () => {
  const { isTabAllowed } = loadModule()
  assert.equal(isTabAllowed('admin', 'admin'), true)
  assert.equal(isTabAllowed('admin', 'user'), false)
  assert.equal(isTabAllowed('note', 'user'), true)
})

test('App initializes and persists its active workspace through the helper', () => {
  const app = fs.readFileSync(path.resolve(__dirname, '../src/App.tsx'), 'utf8')
  assert.match(app, /useState<ActiveTab>\(readActiveTab\)/)
  assert.match(app, /saveActiveTab\(activeTab\)/)
  assert.match(app, /isTabAllowed\(activeTab, authUser\.role\)/)
})
