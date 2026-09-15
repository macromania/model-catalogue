import { useSyncExternalStore } from 'react'

function subscribe(callback: () => void) {
  window.addEventListener('popstate', callback)
  return () => window.removeEventListener('popstate', callback)
}

export const useQuery = () => useSyncExternalStore(subscribe, () => window.location.search)

export function navigate(params: URLSearchParams) {
  const query = params.toString()
  window.history.pushState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}`)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

export function changeParameter(query: string, key: string, value: string | null) {
  const next = new URLSearchParams(query)
  if (value === null) next.delete(key)
  else next.set(key, value)
  navigate(next)
}
