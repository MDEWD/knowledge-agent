import type { ActiveTab } from './types'

export const ACTIVE_TAB_STORAGE_KEY = 'zhiyan.activeTab'

const ACTIVE_TABS: ReadonlySet<string> = new Set([
  'add',
  'import',
  'note',
  'ai',
  'deep',
  'stats',
  'admin',
])

interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export function readActiveTab(storage: StorageLike = window.localStorage): ActiveTab {
  try {
    const saved = storage.getItem(ACTIVE_TAB_STORAGE_KEY)
    return saved && ACTIVE_TABS.has(saved) ? saved as ActiveTab : 'add'
  } catch {
    return 'add'
  }
}

export function saveActiveTab(tab: ActiveTab, storage: StorageLike = window.localStorage): void {
  try {
    storage.setItem(ACTIVE_TAB_STORAGE_KEY, tab)
  } catch {
    // Storage can be unavailable in hardened/private browser contexts.
  }
}

export function isTabAllowed(tab: ActiveTab, role: 'user' | 'admin'): boolean {
  return tab !== 'admin' || role === 'admin'
}
