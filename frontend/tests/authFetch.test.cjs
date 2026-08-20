const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const vm = require('node:vm')

function loadModule() {
  const filename = path.resolve(__dirname, '../src/api/authFetch.ts')
  const source = fs.readFileSync(filename, 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(output, { module, exports: module.exports, Request, Response, URL, Promise, setTimeout, fetch })
  return module.exports
}

async function main() {
  const { createAuthenticatedFetch } = loadModule()
  let refreshCalls = 0
  let resourceCalls = 0
  const fetchMock = async (input) => {
    if (String(input) === '/api/auth/refresh') {
      refreshCalls += 1
      await new Promise((resolve) => setTimeout(resolve, 5))
      return new Response(JSON.stringify({ user: { id: 'u1' } }), { status: 200 })
    }
    resourceCalls += 1
    return new Response('{}', { status: resourceCalls <= 2 ? 401 : 200 })
  }
  const client = createAuthenticatedFetch(fetchMock)
  const [first, second] = await Promise.all([
    client.authenticatedFetch('/resource-a'),
    client.authenticatedFetch('/resource-b'),
  ])
  assert.equal(first.status, 200)
  assert.equal(second.status, 200)
  assert.equal(refreshCalls, 1, 'concurrent 401 responses must share one refresh request')
  assert.equal(resourceCalls, 4, 'both protected requests must be replayed after refresh')
  console.log('authFetch regression passed')
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
