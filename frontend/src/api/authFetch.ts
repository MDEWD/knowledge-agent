import type { AuthUser } from '../types'

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

interface RefreshPayload {
  user: AuthUser
}

/**
 * Build a fetch wrapper that rotates an expired access cookie once and then
 * replays every protected request that was waiting on the same refresh.
 */
export function createAuthenticatedFetch(
  fetchImpl: FetchLike,
  refreshUrl = '/api/auth/refresh',
) {
  let refreshInFlight: Promise<RefreshPayload> | null = null

  const refreshSession = (): Promise<RefreshPayload> => {
    if (!refreshInFlight) {
      refreshInFlight = (async () => {
        const response = await fetchImpl(refreshUrl, {
          method: 'POST',
          credentials: 'same-origin',
        })
        if (!response.ok) throw new Error('登录状态已失效，请重新登录')
        return response.json() as Promise<RefreshPayload>
      })().finally(() => {
        refreshInFlight = null
      })
    }
    return refreshInFlight
  }

  const authenticatedFetch: FetchLike = async (input, init = {}) => {
    const options: RequestInit = { credentials: 'same-origin', ...init }
    const retryInput = input instanceof Request ? input.clone() : input
    const response = await fetchImpl(input, options)
    if (response.status !== 401 || String(input).includes(refreshUrl)) return response

    try {
      await refreshSession()
    } catch {
      return response
    }
    return fetchImpl(retryInput, options)
  }

  return { authenticatedFetch, refreshSession }
}

const authFetchClient = createAuthenticatedFetch(fetch.bind(globalThis))

export const authenticatedFetch = authFetchClient.authenticatedFetch
export const refreshSessionRequest = authFetchClient.refreshSession
