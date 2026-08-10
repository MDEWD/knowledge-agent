import AgentPanel from './AgentPanel'

interface Props {
  sessionId: string | null
  sessionSelectionKey: number
  onSessionSaved: (sessionId: string) => void
  onNewSession: () => void
  onRunningChange: (running: boolean) => void
}

export default function DeepResearchPanel({
  sessionId,
  sessionSelectionKey,
  onSessionSaved,
  onNewSession,
  onRunningChange,
}: Props) {
  return (
    <div className="h-full min-h-0 overflow-hidden">
      <AgentPanel
        fixedMode="deep"
        deepSessionId={sessionId}
        deepSessionSelectionKey={sessionSelectionKey}
        onDeepSessionSaved={onSessionSaved}
        onDeepNewSession={onNewSession}
        onRunningChange={onRunningChange}
      />
    </div>
  )
}
