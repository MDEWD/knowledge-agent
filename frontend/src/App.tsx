import { useEffect, useState } from 'react'
import VideoInput from './components/VideoInput'
import VideoLibrary from './components/VideoLibrary'
import AiPanel from './components/AiPanel'
import NoteEditor from './components/NoteEditor'
import StatsPanel from './components/StatsPanel'
import ReviewPanel from './components/ReviewPanel'
import RecommendationsPanel from './components/RecommendationsPanel'
import ArticlePanel from './components/ArticlePanel'
import RecallPanel from './components/RecallPanel'
import GraphPanel from './components/GraphPanel'
import MemorySidebar from './components/MemorySidebar'
import NoteImportPanel from './components/NoteImportPanel'
import { fetchVideos, fetchImportedNotes } from './api/client'
import type { ActiveTab, ImportedNote, Video } from './types'

export default function App() {
  const [videos, setVideos] = useState<Video[]>([])
  const [importedNotes, setImportedNotes] = useState<ImportedNote[]>([])
  const [activeTab, setActiveTab] = useState<ActiveTab>('add')
  const [selectedVideo, setSelectedVideo] = useState<Video | null>(null)
  const [prefillUrl, setPrefillUrl] = useState('')
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

  const TABS: { id: ActiveTab; label: string; disabled?: boolean }[] = [
    { id: 'add', label: '添加视频' },
    { id: 'import', label: '导入笔记' },
    { id: 'ai', label: 'AI 对话' },
    { id: 'note', label: '笔记', disabled: !selectedVideo },
    { id: 'article', label: '综合文章' },
    { id: 'recall', label: '主动回忆' },
    { id: 'graph', label: '知识图谱' },
    { id: 'review', label: '复盘' },
    { id: 'stats', label: '统计' },
  ]

  return (
    <div className="flex h-screen bg-gray-900 text-white overflow-hidden">
      {/* Sidebar */}
      <aside className="w-72 border-r border-gray-800 flex flex-col p-4 shrink-0">
        <div className="mb-5 flex items-start justify-between">
          <div>
            <h1 className="text-base font-bold text-white">知识库 Agent</h1>
            <p className="text-xs text-gray-500 mt-0.5">视频 → 笔记 → 对话</p>
          </div>
          <button
            onClick={() => setIsDark((v) => !v)}
            className="mt-0.5 text-gray-500 hover:text-gray-300 transition-colors text-lg leading-none"
            title={isDark ? '切换到浅色模式' : '切换到深色模式'}
          >
            {isDark ? '☀️' : '🌙'}
          </button>
        </div>
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

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Tabs */}
        <div className="flex border-b border-gray-800 px-6 shrink-0">
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
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden p-6 min-h-0">
          {/* AiPanel always mounted to preserve chat history */}
          <div className={`h-full flex flex-col min-h-0 ${activeTab === 'ai' ? '' : 'hidden'}`}>
            <AiPanel suggestedVideo={selectedVideo} />
          </div>
          {activeTab === 'add' && (
            <div className="max-w-2xl space-y-5 overflow-y-auto h-full pb-4">
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
          )}
          {activeTab === 'note' && selectedVideo && (
            <NoteEditor
              key={selectedVideo.id}
              video={selectedVideo}
              allVideos={videos}
              onSelectVideo={handleSelectVideo}
            />
          )}
          {activeTab === 'stats' && <StatsPanel />}
          {activeTab === 'article' && <ArticlePanel />}
          {activeTab === 'review' && <ReviewPanel />}
          {activeTab === 'recall' && <RecallPanel videos={videos} />}
          {activeTab === 'graph' && <GraphPanel />}
          {activeTab === 'import' && (
            <div className="max-w-2xl h-full overflow-y-auto">
              <NoteImportPanel onNoteAdded={() => fetchImportedNotes().then(setImportedNotes).catch(console.error)} />
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
