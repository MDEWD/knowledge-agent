const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const frontendRoot = path.resolve(__dirname, '..')
const adminPanel = fs.readFileSync(path.join(frontendRoot, 'src/components/AdminPanel.tsx'), 'utf8')
const styles = fs.readFileSync(path.join(frontendRoot, 'src/index.css'), 'utf8')

test('admin surfaces have explicit light-theme styling', () => {
  assert.match(adminPanel, /className="admin-panel\b/)
  assert.ok((adminPanel.match(/admin-surface/g) || []).length >= 3)
  assert.match(styles, /html\.light \.admin-panel \.admin-surface\s*\{[^}]*background-color:\s*#ffffff\s*!important;/s)
  assert.match(styles, /html\.light \.admin-panel \.admin-filter-surface\s*\{[^}]*background-color:\s*#f8fafc\s*!important;/s)
  assert.match(styles, /html\.light \.admin-panel \.admin-table-row:hover\s*\{[^}]*background-color:\s*#f8fafc\s*!important;/s)
})

test('admin selects render a chevron directly beside the selected label', () => {
  assert.match(adminPanel, /md:grid-cols-\[1fr_auto_auto_auto\]/)
  assert.match(adminPanel, /function CompactSelect/)
  assert.ok((adminPanel.match(/<CompactSelect\b/g) || []).length >= 3)
  assert.match(adminPanel, /admin-compact-select[^"']*gap-1/)
  assert.match(adminPanel, /className="absolute inset-0 h-full w-full cursor-pointer opacity-0/)
  assert.doesNotMatch(styles, /\.admin-panel \.admin-(?:filter|role)-select/)
})

test('mobile admin view prioritizes user cards and collapses filters', () => {
  assert.match(adminPanel, /\[mobileFiltersOpen, setMobileFiltersOpen\] = useState\(false\)/)
  assert.match(adminPanel, /admin-mobile-filter-toggle/)
  assert.match(adminPanel, /aria-expanded=\{mobileFiltersOpen\}/)
  assert.match(adminPanel, /admin-mobile-filters/)
  assert.match(adminPanel, /admin-mobile-users[^"']*md:hidden/)
  assert.match(adminPanel, /admin-desktop-users[^"']*hidden[^"']*md:block/)
})

test('admin status badges use bright semantic colors in light mode', () => {
  assert.match(adminPanel, /admin-status-active/)
  assert.match(adminPanel, /admin-status-pending/)
  assert.match(adminPanel, /admin-status-suspended/)
  assert.match(styles, /html\.light \.admin-panel \.admin-status-active\s*\{[^}]*background-color:\s*#dcfce7\s*!important;/s)
  assert.match(styles, /html\.light \.admin-panel \.admin-status-pending\s*\{[^}]*background-color:\s*#fef3c7\s*!important;/s)
  assert.match(styles, /html\.light \.admin-panel \.admin-status-suspended\s*\{[^}]*background-color:\s*#fee2e2\s*!important;/s)
})
