import type { ReactNode } from 'react'
import { safeUrl } from './data'

export function Feedback({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return <div className={`feedback${error ? ' error' : ''}`} role={error ? 'alert' : 'status'}>{children}</div>
}

export function Loading() {
  return <div className="loading" role="status" aria-label="Loading catalogue">
    <span>Loading catalogue...</span><div /><div /><div />
  </div>
}

export function ExternalLink({ href, children }: { href: unknown; children: ReactNode }) {
  const url = safeUrl(href)
  return url ? <a href={url} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>
}
