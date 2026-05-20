import { useState } from 'react'
import ChatInterface from './ChatInterface'
import AgentPanel from './AgentPanel'
import type { Video } from '../types'

type Mode = 'chat' | 'agent'

interface Props {
  suggestedVideo: Video | null
}

export default function AiPanel({ suggestedVideo }: Props) {
  const [mode, setMode] = useState<Mode>('chat')

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* Mode toggle */}
      <div className="flex items-center gap-1 mb-4 bg-gray-800 rounded-xl p-1 w-fit shrink-0">
        <button
          onClick={() => setMode('chat')}
          className={`px-4 py-1.5 text-sm font-medium rounded-lg transition-colors ${
            mode === 'chat'
              ? 'bg-gray-700 text-white shadow-sm'
              : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          快速对话
        </button>
        <button
          onClick={() => setMode('agent')}
          className={`px-4 py-1.5 text-sm font-medium rounded-lg transition-colors ${
            mode === 'agent'
              ? 'bg-gray-700 text-white shadow-sm'
              : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          深度分析
        </button>
      </div>

      {/* Panels — both stay mounted to preserve state */}
      <div className={`flex-1 flex flex-col min-h-0 ${mode === 'chat' ? '' : 'hidden'}`}>
        <ChatInterface suggestedVideo={suggestedVideo} />
      </div>
      <div className={`flex-1 overflow-y-auto min-h-0 ${mode === 'agent' ? '' : 'hidden'}`}>
        <AgentPanel />
      </div>
    </div>
  )
}
