import { useCallback, useEffect, useState } from 'react'
import VideoInput from './components/VideoInput'
import VideoLibrary from './components/VideoLibrary'
import AiPanel from './components/AiPanel'
import NoteEditor from './components/NoteEditor'
import StatsPanel from './components/StatsPanel'
import RecommendationsPanel from './components/RecommendationsPanel'
import DeepResearchPanel from './components/DeepResearchPanel'
import GlobalMemoryDrawer from './components/GlobalMemoryDrawer'
import NoteImportPanel from './components/NoteImportPanel'
import ImportedNoteEditor from './components/ImportedNoteEditor'
import DeepResearchHistorySidebar from './components/DeepResearchHistorySidebar'
import AuthPage from './components/AuthPage'
import AdminPanel from './components/AdminPanel'
import { fetchVideos, fetchImportedNotes, fetchCurrentUser, refreshAuthSession, logoutAuthSession } from './api/client'
import { isTabAllowed, readActiveTab, saveActiveTab } from './tabPersistence'
import type { ActiveTab, AuthUser, ImportedNote, Video } from './types'

export default function App() {
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [videos, setVideos] = useState<Video[]>([])
  const [importedNotes, setImportedNotes] = useState<ImportedNote[]>([])
  const [activeTab, setActiveTab] = useState<ActiveTab>(readActiveTab)
  const [selectedVideo, setSelectedVideo] = useState<Video | null>(null)
  const [selectedImportedNote, setSelectedImportedNote] = useState<ImportedNote | null>(null)
  const [prefillUrl, setPrefillUrl] = useState('')
  const [activeDeepSessionId, setActiveDeepSessionId] = useState<string | null>(null)
  const [deepSessionSelectionKey, setDeepSessionSelectionKey] = useState(0)
  const [deepHistoryRefreshKey, setDeepHistoryRefreshKey] = useState(0)
  const [deepResearchRunning, setDeepResearchRunning] = useState(false)
  const [deepHistoryOpen, setDeepHistoryOpen] = useState(false)
  const [memoryDrawerOpen, setMemoryDrawerOpen] = useState(false)
  const hasSelectedNote = Boolean(selectedVideo || selectedImportedNote)
  const [isDark, setIsDark] = useState(() => {
    const saved = localStorage.getItem('theme')
    return saved ? saved === 'dark' : true
  })

  useEffect(() => {
    if (isDark) {
      document.documentElement.classList.remove('light')
    } else {
      document.documentElement.classList.add('light')
    }
    localStorage.setItem('theme', isDark ? 'dark' : 'light')
  }, [isDark])

  useEffect(() => {
    saveActiveTab(activeTab)
  }, [activeTab])

  useEffect(() => {
    if (authUser && !isTabAllowed(activeTab, authUser.role)) {
      setActiveTab('add')
    }
  }, [activeTab, authUser])

  useEffect(() => {
    if (activeTab !== 'deep') setDeepHistoryOpen(false)
  }, [activeTab])

  useEffect(() => {
    let cancelled = false
    const restore = async () => {
      try {
        let user: AuthUser
        try {
          user = await fetchCurrentUser()
        } catch {
          user = await refreshAuthSession()
        }
        if (!cancelled) setAuthUser(user)
      } catch {
        if (!cancelled) setAuthUser(null)
      } finally {
        if (!cancelled) setAuthLoading(false)
      }
    }
    void restore()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!authUser) return
    fetchVideos().then(setVideos).catch(console.error)
    fetchImportedNotes().then(setImportedNotes).catch(console.error)
  }, [authUser?.id])

  useEffect(() => {
    if (!authUser) return
    const interval = window.setInterval(() => {
      refreshAuthSession().then(setAuthUser).catch(() => setAuthUser(null))
    }, 20 * 60 * 1000)
    return () => window.clearInterval(interval)
  }, [authUser?.id])

  const handleNewVideo = (video: Video) => {
    setVideos((prev) => {
      const filtered = prev.filter((v) => v.id !== video.id)
      return [video, ...filtered]
    })
  }

  const handleSelectVideo = (video: Video) => {
    setSelectedVideo(video)
    setSelectedImportedNote(null)
    setActiveTab('note')
  }

  const handleSelectImportedNote = (note: ImportedNote) => {
    setSelectedImportedNote(note)
    setSelectedVideo(null)
    setActiveTab('note')
  }

  const handleSelectDeepSession = (sessionId: string) => {
    if (deepResearchRunning) return
    setActiveDeepSessionId(sessionId)
    setDeepSessionSelectionKey((value) => value + 1)
    setDeepHistoryOpen(false)
  }

  const handleNewDeepSession = () => {
    if (deepResearchRunning) return
    setActiveDeepSessionId(null)
    setDeepSessionSelectionKey((value) => value + 1)
    setDeepHistoryOpen(false)
  }

  const handleDeepSessionSaved = (sessionId: string) => {
    setActiveDeepSessionId(sessionId)
    setDeepHistoryRefreshKey((value) => value + 1)
  }

  const handleDeepRunningChange = useCallback((isRunning: boolean) => {
    setDeepResearchRunning(isRunning)
    // After a full browser refresh, the DeepResearch panel reconnects in the
    // background. Bring the user back to the live run instead of the default tab.
    if (isRunning) setActiveTab('deep')
  }, [])

  const handleLogout = async () => {
    try {
      await logoutAuthSession()
    } finally {
      setAuthUser(null)
      setVideos([])
      setImportedNotes([])
      setSelectedVideo(null)
      setSelectedImportedNote(null)
      setActiveDeepSessionId(null)
      setActiveTab('add')
    }
  }

  const TABS: { id: ActiveTab; label: string; disabled?: boolean }[] = [
    { id: 'add', label: '添加视频' },
    { id: 'import', label: '导入笔记' },
    { id: 'note', label: '笔记' },
    { id: 'ai', label: 'AI 对话' },
    { id: 'deep', label: '深度研究' },
    { id: 'stats', label: '统计' },
    ...(authUser?.role === 'admin' ? [{ id: 'admin' as ActiveTab, label: '用户管理' }] : []),
  ]

  if (authLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-900 text-sm text-gray-500">
        <div className="flex items-center gap-3"><span className="h-5 w-5 animate-spin rounded-full border-2 border-gray-700 border-t-cyan-400" />正在恢复登录状态…</div>
      </div>
    )
  }

  if (!authUser) {
    return <AuthPage onAuthenticated={setAuthUser} isDark={isDark} onToggleTheme={() => setIsDark((value) => !value)} />
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-gray-900 text-white">
      {/* Global navigation */}
      <header className="flex h-14 shrink-0 items-stretch border-b border-gray-800">
        <div className="flex shrink-0 items-center px-3 md:w-72 md:px-5">
          <h1 className="whitespace-nowrap text-sm font-bold text-white md:text-base">知研 Agent</h1>
        </div>
        <nav className="flex min-w-0 flex-1 overflow-x-auto scrollbar-hide px-2 md:px-4">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => !tab.disabled && setActiveTab(tab.id)}
              disabled={tab.disabled}
              className={`px-4 py-3.5 text-sm font-medium whitespace-nowrap shrink-0 border-b-2 transition-colors -mb-px disabled:opacity-30 disabled:cursor-not-allowed ${
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-gray-500 hover:text-gray-300'
              }`}
            >
              {tab.label}
              {tab.id === 'note' && selectedVideo && (
                <span className="ml-1.5 text-[10px] text-gray-500 truncate max-w-[100px] inline-block align-middle">
                  · {selectedVideo.title.slice(0, 12)}…
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="flex shrink-0 items-center gap-1.5 px-2 md:gap-2 md:px-4">
          <div className="hidden min-w-0 text-right lg:block">
            <p className="max-w-40 truncate text-xs font-medium text-gray-300">{authUser.display_name || authUser.email}</p>
            <p className="max-w-40 truncate text-[10px] text-gray-600">{authUser.email}</p>
          </div>
          <button
            onClick={() => setMemoryDrawerOpen(true)}
            className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-800 hover:text-purple-300"
            title="长期记忆"
            aria-label="打开长期记忆"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9.5 4.5A3.5 3.5 0 0 0 6 8v.4A3.5 3.5 0 0 0 4.5 15a3.5 3.5 0 0 0 5 4.5" />
              <path d="M14.5 4.5A3.5 3.5 0 0 1 18 8v.4a3.5 3.5 0 0 1 1.5 6.6 3.5 3.5 0 0 1-5 4.5" />
              <path d="M9.5 4.5a3 3 0 0 1 5 0v15a3 3 0 0 1-5 0zM9.5 9H7.8M14.5 14h1.7" />
            </svg>
          </button>
          <button
            onClick={() => setIsDark((v) => !v)}
            className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-800 hover:text-gray-300"
            title={isDark ? '切换到浅色模式' : '切换到深色模式'}
          >
            {isDark ? (
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
              </svg>
            ) : (
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </svg>
            )}
          </button>
          <button
            onClick={() => void handleLogout()}
            className="rounded-lg border border-gray-800 px-3 py-2 text-xs text-gray-500 transition hover:border-gray-700 hover:bg-gray-800 hover:text-gray-300"
          >
            退出
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Notes navigation only belongs to the notes workspace. */}
        {activeTab === 'note' && (
          <aside className={`note-mobile-list ${hasSelectedNote ? 'hidden md:flex' : 'flex'} w-full shrink-0 flex-col border-r border-gray-800 p-4 md:w-72`}>
            <div className="flex-1 min-h-0">
              <VideoLibrary
                videos={videos}
                onDelete={(id) => setVideos((prev) => prev.filter((v) => v.id !== id))}
                onSelectVideo={handleSelectVideo}
                notes={importedNotes}
                onSelectNote={handleSelectImportedNote}
              />
            </div>
          </aside>
        )}
        {activeTab === 'deep' && (
          <>
            {deepHistoryOpen && <button type="button" aria-label="关闭研究会话" onClick={() => setDeepHistoryOpen(false)} className="deep-history-mobile-backdrop fixed inset-x-0 bottom-0 top-14 z-40 bg-black/40 backdrop-blur-[1px] md:hidden" />}
            <DeepResearchHistorySidebar
              activeSessionId={activeDeepSessionId}
              refreshKey={deepHistoryRefreshKey}
              disabled={deepResearchRunning}
              mobileOpen={deepHistoryOpen}
              onMobileClose={() => setDeepHistoryOpen(false)}
              onSelect={handleSelectDeepSession}
              onNew={handleNewDeepSession}
            />
          </>
        )}

        {/* Main */}
        <main className={`${activeTab === 'note' && !hasSelectedNote ? 'hidden md:flex' : 'flex'} min-w-0 flex-1 flex-col`}>

        {/* Content */}
        <div className="flex-1 overflow-hidden p-3 min-h-0 md:p-6">
          {/* AiPanel always mounted to preserve chat history */}
          <div className={`h-full flex flex-col min-h-0 ${activeTab === 'ai' ? '' : 'hidden'}`}>
            <AiPanel suggestedVideo={selectedVideo} />
          </div>
          {/* DeepResearch always stays mounted so switching tabs does not lose a running report. */}
          <div className={`h-full flex-col min-h-0 ${activeTab === 'deep' ? 'flex' : 'hidden'}`}>
            <button type="button" onClick={() => setDeepHistoryOpen(true)} className="deep-history-mobile-trigger mb-3 flex shrink-0 items-center justify-center gap-2 rounded-xl border border-gray-700 bg-gray-800/50 px-3 py-2.5 text-sm text-gray-300 md:hidden">
              <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="h-4 w-4"><path d="M4 5h12M4 10h12M4 15h8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>
              研究会话
            </button>
            <div className="min-h-0 flex-1">
              <DeepResearchPanel
                sessionId={activeDeepSessionId}
                sessionSelectionKey={deepSessionSelectionKey}
                onSessionSaved={handleDeepSessionSaved}
                onNewSession={handleNewDeepSession}
                onRunningChange={handleDeepRunningChange}
              />
            </div>
          </div>
          {activeTab === 'add' && (
            <div className="h-full overflow-y-auto pb-4">
              <div className="mx-auto w-full max-w-4xl space-y-6">
                <VideoInput
                  onDone={handleNewVideo}
                  prefillUrl={prefillUrl}
                  onClearPrefill={() => setPrefillUrl('')}
                />
                <RecommendationsPanel
                  hasVideos={videos.length > 0}
                  onAddVideo={(url) => setPrefillUrl(url)}
                />
              </div>
            </div>
          )}
          {activeTab === 'note' && hasSelectedNote && (
            <div className="note-mobile-detail flex h-full min-h-0 flex-col">
              <button type="button" onClick={() => { setSelectedVideo(null); setSelectedImportedNote(null) }} className="note-mobile-back mb-3 flex shrink-0 items-center gap-1.5 self-start rounded-lg border border-gray-700 px-3 py-2 text-sm text-gray-400 md:hidden">
                <span aria-hidden="true">←</span> 返回笔记列表
              </button>
              <div className="min-h-0 flex-1">
                {selectedVideo && <NoteEditor key={selectedVideo.id} video={selectedVideo} allVideos={videos} onSelectVideo={handleSelectVideo} />}
                {selectedImportedNote && <ImportedNoteEditor note={selectedImportedNote} />}
              </div>
            </div>
          )}
          {activeTab === 'note' && !selectedVideo && !selectedImportedNote && (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              从左侧选择一条笔记
            </div>
          )}
          {activeTab === 'stats' && <StatsPanel />}
          {activeTab === 'admin' && authUser.role === 'admin' && <AdminPanel currentUser={authUser} />}
          {activeTab === 'import' && (
            <div className="h-full overflow-hidden">
              <NoteImportPanel onNoteAdded={() => fetchImportedNotes().then(setImportedNotes).catch(console.error)} />
            </div>
          )}
        </div>
        </main>
      </div>
      <GlobalMemoryDrawer open={memoryDrawerOpen} onClose={() => setMemoryDrawerOpen(false)} />
    </div>
  )
}
