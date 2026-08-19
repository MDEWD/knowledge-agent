interface DeepSessionSignals {
  running: boolean
  result: string
  historyLength: number
  currentQuestion: string
  runId: string
}

interface DeepResearchTurn {
  question: string
  answer: string
}

/** The initial composer is only valid before a research question is submitted. */
export function hasDeepSession(signals: DeepSessionSignals): boolean {
  return Boolean(
    signals.running
    || signals.result.trim()
    || signals.historyLength > 0
    || signals.currentQuestion.trim()
    || signals.runId.trim()
  )
}

/** Prefer an existing selected session for follow-ups; only create on blank pages. */
export function resolveDeepSessionId(
  localSessionId: string,
  selectedSessionId: string | null | undefined,
  generatedSessionId: string,
): string {
  return selectedSessionId?.trim() || localSessionId.trim() || generatedSessionId
}

/** Keep the visible completed report when local persistence refresh was delayed. */
export function prepareFollowUpHistory(
  history: DeepResearchTurn[],
  currentQuestion: string,
  currentAnswer: string,
): DeepResearchTurn[] {
  const question = currentQuestion.trim()
  const answer = currentAnswer.trim()
  const next = history.map((turn) => ({ ...turn }))
  if (!question || !answer) return next

  const latest = next[next.length - 1]
  if (latest?.question.trim() === question) {
    if (!latest.answer.trim()) latest.answer = currentAnswer
    return next
  }
  next.push({ question: currentQuestion, answer: currentAnswer })
  return next
}
