import { useQuery } from '@tanstack/react-query'
import { api } from './client'

/** Server readiness, shared by the header badge, the global banner and the demo callout. */
export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => api.health(signal),
    retry: 0,
    refetchOnWindowFocus: true,
    // Check again quickly while the server is down so the banner clears as soon as it is back.
    refetchInterval: (query) => (query.state.status === 'error' ? 5000 : 30000),
  })
}

export type ServerProblem = 'down' | 'worker' | null

/** What (if anything) people should be told about the server, from the readiness probe. */
export function serverProblem(health: ReturnType<typeof useHealth>): ServerProblem {
  if (health.isError) return 'down'
  const data = health.data
  if (!data) return null
  if (data.status === 'unavailable' || data.redis === false) return 'down'
  if (data.worker === false) return 'worker'
  return null
}
