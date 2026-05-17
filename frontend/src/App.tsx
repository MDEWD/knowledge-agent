import { useEffect, useState } from 'react'
import VideoInput from './components/VideoInput'
import VideoLibrary from './components/VideoLibrary'
import ChatInterface from './components/ChatInterface'
import { fetchVideos } from './api/client'
import type { ActiveTab, Video } from './types'

export default function App() {
  const [videos, setVideos] = useState<Video[]>([])
  const [activeTab, setActiveTab] = useState<ActiveTab>('add')
  const [selectedVideo, setSelectedVideo] = useState<Video | null>(null)

  useEffect(() => {
    fetchVideos()
      .then(setVideos)
      .catch(console.error)
  }, [])

  const handleNewVideo = (video: Video) => {
    setVideos((prev) => {
      const filtered = prev.filter((v) => v.id !== video.id)
      return [video, ...filtered]
    })
  }

  const handleSelectVideo = (video: Video) => {
    setSelectedVideo(video)
    setActiveTab('chat')
  }

  return (
    <div className="flex h-screen bg-gray-900 text-white overflow-hidden">
      {/* Sidebar */}
      <aside className="w-72 border-r border-gray-800 flex flex-col p-4 shrink-0">
        <div className="mb-5">
          <h1 className="text-base font-bold text-white">知识库 Agent</h1>
          <p className="text-xs text-gray-500 mt-0.5">视频 → 笔记 → 对话</p>
        </div>
        <div className="flex-1 min-h-0">
          <VideoLibrary
            videos={videos}
            onDelete={(id) => setVideos((prev) => prev.filter((v) => v.id !== id))}
            onSelectVideo={handleSelectVideo}
          />
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Tabs */}
        <div className="flex border-b border-gray-800 px-6 shrink-0">
          {(['add', 'chat'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-3.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
                activeTab === tab
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-gray-500 hover:text-gray-300'
              }`}
            >
              {tab === 'add' ? '添加视频' : '知识对话'}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden p-6 min-h-0">
          {activeTab === 'add' ? (
            <div className="max-w-2xl">
              <VideoInput onDone={handleNewVideo} />
            </div>
          ) : (
            <div className="h-full flex flex-col">
              <ChatInterface suggestedVideo={selectedVideo} />
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
