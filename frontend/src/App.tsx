import { useEffect, useState } from 'react'
import VideoInput from './components/VideoInput'
import VideoLibrary from './components/VideoLibrary'
import AiPanel from './components/AiPanel'
import NoteEditor from './components/NoteEditor'
import StatsPanel from './components/StatsPanel'
import RecommendationsPanel from './components/RecommendationsPanel'
import DeepResearchPanel from './components/DeepResearchPanel'
import MemorySidebar from './components/MemorySidebar'
import NoteImportPanel from './components/NoteImportPanel'
import DeepResearchHistorySidebar from './components/DeepResearchHistorySidebar'
import { fetchVideos, fetchImportedNotes } from './api/client'
import type { ActiveTab, ImportedNote, Video } from './types'

export default function App() {
  const [videos, setVideos] = useState<Video[]>([])
  const [importedNotes, setImportedNotes] = useState<ImportedNote[]>([])
  const [activeTab, setActiveTab] = useState<ActiveTab>('add')
  const [selectedVideo, setSelectedVideo] = useState<Video | null>(null)
  const [prefillUrl, setPrefillUrl] = useState('')
  const [activeDeepSessionId, setActiveDeepSessionId] = useState<string | null>(null)
  const [deepSessionSelectionKey, setDeepSessionSelectionKey] = useState(0)
  const [deepHistoryRefreshKey, setDeepHistoryRefreshKey] = useState(0)
  const [deepResearchRunning, setDeepResearchRunning] = useState(false)
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
    fetchVideos().then(setVideos).catch(console.error)
    fetchImportedNotes().then(setImportedNotes).catch(console.error)
  }, [])

  const handleNewVideo = (video: Video) => {
    setVideos((prev) => {
      const filtered = prev.filter((v) => v.id !== video.id)
      return [video, ...filtered]
    })
  }

  const handleSelectVideo = (video: Video) => {
    setSelectedVideo(video)
    setActiveTab('note')
  }

  const handleSelectDeepSession = (sessionId: string) => {
    if (deepResearchRunning) return
    setActiveDeepSessionId(sessionId)
    setDeepSessionSelectionKey((value) => value + 1)
  }

  const handleNewDeepSession = () => {
    if (deepResearchRunning) return
    setActiveDeepSessionId(null)
    setDeepSessionSelectionKey((value) => value + 1)
  }

  const handleDeepSessionSaved = (sessionId: string) => {
    setActiveDeepSessionId(sessionId)
    setDeepHistoryRefreshKey((value) => value + 1)
  }

  const TABS: { id: ActiveTab; label: string; disabled?: boolean }[] = [
    { id: 'add', label: '添加视频' },
    { id: 'import', label: '导入笔记' },
    { id: 'note', label: '笔记' },
    { id: 'ai', label: 'AI 对话' },
    { id: 'deep', label: '深度研究' },
    { id: 'stats', label: '统计' },
  ]

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-gray-900 text-white">
      {/* Global navigation */}
      <header className="flex h-14 shrink-0 items-stretch border-b border-gray-800">
        <div className="flex w-72 shrink-0 items-center px-5">
          <h1 className="text-base font-bold text-white">智能 Agent 工作台</h1>
        </div>
        <nav className="flex min-w-0 flex-1 overflow-x-auto px-4">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => !tab.disabled && setActiveTab(tab.id)}
              disabled={tab.disabled}
              className={`px-4 py-3.5 text-sm font-medium border-b-2 transition-colors -mb-px disabled:opacity-30 disabled:cursor-not-allowed ${
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
        <button
          onClick={() => setIsDark((v) => !v)}
          className="mx-4 self-center text-lg leading-none text-gray-500 transition-colors hover:text-gray-300"
          title={isDark ? '切换到浅色模式' : '切换到深色模式'}
        >
          {isDark ? '☀️' : '🌙'}
        </button>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Notes navigation only belongs to the notes workspace. */}
        {activeTab === 'note' && (
          <aside className="flex w-72 shrink-0 flex-col border-r border-gray-800 p-4">
            <div className="flex-1 min-h-0">
              <VideoLibrary
                videos={videos}
                onDelete={(id) => setVideos((prev) => prev.filter((v) => v.id !== id))}
                onSelectVideo={handleSelectVideo}
                notes={importedNotes}
                onSelectNote={() => setActiveTab('import')}
              />
            </div>
            <MemorySidebar />
          </aside>
        )}
        {activeTab === 'deep' && (
          <DeepResearchHistorySidebar
            activeSessionId={activeDeepSessionId}
            refreshKey={deepHistoryRefreshKey}
            disabled={deepResearchRunning}
            onSelect={handleSelectDeepSession}
            onNew={handleNewDeepSession}
          />
        )}

        {/* Main */}
        <main className="flex min-w-0 flex-1 flex-col">

        {/* Content */}
        <div className="flex-1 overflow-hidden p-6 min-h-0">
          {/* AiPanel always mounted to preserve chat history */}
          <div className={`h-full flex flex-col min-h-0 ${activeTab === 'ai' ? '' : 'hidden'}`}>
            <AiPanel suggestedVideo={selectedVideo} />
          </div>
          {/* DeepResearch always stays mounted so switching tabs does not lose a running report. */}
          <div className={`h-full flex flex-col min-h-0 ${activeTab === 'deep' ? '' : 'hidden'}`}>
            <DeepResearchPanel
              sessionId={activeDeepSessionId}
              sessionSelectionKey={deepSessionSelectionKey}
              onSessionSaved={handleDeepSessionSaved}
              onNewSession={handleNewDeepSession}
              onRunningChange={setDeepResearchRunning}
            />
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
          {activeTab === 'note' && selectedVideo && (
            <NoteEditor
              key={selectedVideo.id}
              video={selectedVideo}
              allVideos={videos}
              onSelectVideo={handleSelectVideo}
            />
          )}
          {activeTab === 'note' && !selectedVideo && (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              从左侧选择一条笔记
            </div>
          )}
          {activeTab === 'stats' && <StatsPanel />}
          {activeTab === 'import' && (
            <div className="h-full overflow-hidden">
              <NoteImportPanel onNoteAdded={() => fetchImportedNotes().then(setImportedNotes).catch(console.error)} />
            </div>
          )}
        </div>
        </main>
      </div>
    </div>
  )
}
