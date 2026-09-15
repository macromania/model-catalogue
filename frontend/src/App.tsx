import { useState } from 'react'
import useSWR, { useSWRConfig } from 'swr'
import { CataloguePage } from './features/catalogue/CataloguePage'
import { catalogueKey } from './features/catalogue/query'
import { ModelDetailsPage } from './features/model-details/ModelDetailsPage'
import { ApiError, fetchJson, formatNumber } from './shared/data'
import type { Model, ModelDetail, ModelsPage, Status } from './shared/data'
import { changeParameter, useQuery } from './shared/navigation'
import { ExternalLink, Feedback } from './shared/ui'

export default function App() {
  const query = useQuery()
  const modelId = new URLSearchParams(query).get('model')
  const { data: status, error } = useSWR<Status>('/api/catalogue/status', fetchJson)
  const { mutate } = useSWRConfig()
  const [selected, setSelected] = useState<Model[]>([])
  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const [refreshNotice, setRefreshNotice] = useState<string | null>(null)

  async function refresh() {
    setRefreshing(true)
    setRefreshError(null)
    setRefreshNotice(null)
    try {
      const details = new Map<string, Promise<ModelDetail>>()
      const loadDetail = (id: string) => {
        let request = details.get(id)
        if (!request) {
          request = fetchJson<ModelDetail>(`/api/catalogue/models/${encodeURIComponent(id)}`)
          details.set(id, request)
        }
        return request
      }
      const selectionRefresh = Promise.all(selected.map(async model => {
        try {
          return [model.id, await loadDetail(model.id)] as const
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) return [model.id, null] as const
          throw error
        }
      }))
      const viewKey = modelId ? `/api/catalogue/models/${encodeURIComponent(modelId)}` : catalogueKey(query)
      const [freshStatus, freshView, refreshed] = await Promise.all([
        fetchJson<Status>('/api/catalogue/status'),
        modelId ? loadDetail(modelId) : fetchJson<ModelsPage>(viewKey),
        selectionRefresh,
      ])
      await Promise.all([
        mutate('/api/catalogue/status', freshStatus, { revalidate: false }),
        mutate(viewKey, freshView, { revalidate: false }),
      ])
      const byId = new Map<string, Model | null>(refreshed)
      setSelected(current => {
        const seen = new Set<string>()
        return current.flatMap(model => {
          const updated = byId.has(model.id) ? byId.get(model.id) : model
          if (!updated || seen.has(updated.id)) return []
          seen.add(updated.id)
          return [updated]
        })
      })
      const removed = refreshed.filter(([, model]) => model === null).length
      if (removed) setRefreshNotice(`${removed} previous comparison ${removed === 1 ? 'selection is' : 'selections are'} no longer in this snapshot.`)
    } catch (error) {
      setRefreshError(error instanceof Error ? error.message : 'The view could not be refreshed.')
    } finally { setRefreshing(false) }
  }

  return <>
    <a className="skip-link" href="#main">Skip to content</a>
    <header className="topbar"><a className="app-name" href="/">Model catalogue</a>
      <span className="muted">Azure-first model catalogue</span><button onClick={() => void refresh()} disabled={refreshing}>{refreshing ? 'Refreshing...' : 'Refresh view'}</button></header>
    <main id="main">
      <div className="snapshot">
        {status ? status.seeded_at
          ? <><span>{formatNumber(status.model_count)} models</span><span>Seeded {new Date(status.seeded_at).toLocaleString()}</span></>
          : <span>No seeded snapshot</span>
          : <span>{error ? 'Snapshot metadata unavailable' : 'Loading snapshot metadata...'}</span>}
        {status ? <span>Azure: {status.sources.azure?.status === 'not_configured' || !status.sources.azure ? 'not checked' : `${status.sources.azure.status} import (${status.sources.azure.count} records, ${status.sources.azure.locations.length} regions)`}</span> : null}
      </div>
      {error ? <Feedback error>Could not load snapshot metadata. Check the API and use Refresh view to retry.</Feedback> : null}
      {refreshError ? <Feedback error>{refreshError}</Feedback> : null}
      {refreshNotice ? <Feedback>{refreshNotice}</Feedback> : null}
      {modelId ? <ModelDetailsPage id={modelId} back={() => changeParameter(query, 'model', null)} />
        : <CataloguePage query={query} status={status} selected={selected} setSelected={setSelected} />}
    </main>
    <footer><ExternalLink href="https://models.dev">models.dev</ExternalLink><span>Read-only API and UI. Upstream data is fetched only by the seed program.</span></footer>
  </>
}
