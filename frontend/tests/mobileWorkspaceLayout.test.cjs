const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const app = fs.readFileSync(path.resolve(__dirname, '../src/App.tsx'), 'utf8')
const deepHistory = fs.readFileSync(path.resolve(__dirname, '../src/components/DeepResearchHistorySidebar.tsx'), 'utf8')

test('deep research history becomes an off-canvas drawer on mobile', () => {
  assert.match(app, /\[deepHistoryOpen, setDeepHistoryOpen\] = useState\(false\)/)
  assert.match(app, /deep-history-mobile-trigger[^"']*md:hidden/)
  assert.match(app, /deep-history-mobile-backdrop[^"']*md:hidden/)
  assert.match(deepHistory, /deep-history-sidebar[^"'`]*fixed[^"'`]*md:static/)
  assert.match(deepHistory, /mobileOpen \? 'translate-x-0' : '-translate-x-full'/)
})

test('notes use list-detail navigation instead of side-by-side columns on mobile', () => {
  assert.match(app, /const hasSelectedNote = Boolean\(selectedVideo \|\| selectedImportedNote\)/)
  assert.match(app, /note-mobile-list/)
  assert.match(app, /hasSelectedNote \? 'hidden md:flex' : 'flex'/)
  assert.match(app, /note-mobile-detail/)
  assert.match(app, /note-mobile-back[^"']*md:hidden/)
  assert.match(app, /className="[^"]*\bp-3\b[^"]*"/)
  assert.match(app, /className="[^"]*\bmd:p-6\b[^"]*"/)
})
