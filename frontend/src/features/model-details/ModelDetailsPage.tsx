import { useEffect, useRef } from 'react'
import useSWR from 'swr'
import { fetchJson, formatNumber, formatPrice, record, yesNo } from '../../shared/data'
import type { ModelDetail } from '../../shared/data'
import { ExternalLink, Feedback, Loading } from '../../shared/ui'
import { Benchmarks } from './Benchmarks'
import './model-details.css'
import { AzureSupport } from '../../shared/AzureSupport'

function modalities(raw: Record<string, unknown>, direction: string) {
  const values = record(raw.modalities)?.[direction]
  return Array.isArray(values) ? values.map(String).join(', ') || 'Not reported' : 'Not reported'
}

export function ModelDetailsPage({ id, back }: { id: string; back: () => void }) {
  const { data: model, error, isLoading, mutate } = useSWR<ModelDetail>(`/api/catalogue/models/${encodeURIComponent(id)}`, fetchJson)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { if (model) heading.current?.focus() }, [model])
  return <section>
    <button onClick={back} className="back">Back to catalogue</button>
    {isLoading ? <Loading /> : error ? <Feedback error>{error.message} <button onClick={() => void mutate(undefined, { revalidate: true, populateCache: false, throwOnError: false })}>Retry details</button></Feedback> : model ? <>
      <h1 ref={heading} tabIndex={-1}>{model.name}</h1>
      <p className="model-identity">{model.publisher ?? 'Publisher not reported'} <code>{model.model_id}</code></p>
      <p className="description">{String(model.raw.description ?? model.metadata?.description ?? 'No description supplied.')}</p>
      <dl className="facts">
        <div><dt>Context window</dt><dd>{formatNumber(model.context_tokens)} tokens</dd></div>
        <div><dt>Maximum output</dt><dd>{formatNumber(model.output_tokens)} tokens</dd></div>
        <div><dt>Azure input price</dt><dd>{formatPrice(model.input_price)} / 1M tokens</dd></div>
        <div><dt>Azure output price</dt><dd>{formatPrice(model.output_price)} / 1M tokens</dd></div>
        <div><dt>Input modalities</dt><dd>{modalities(model.raw, 'input')}</dd></div>
        <div><dt>Output modalities</dt><dd>{modalities(model.raw, 'output')}</dd></div>
        <div><dt>Reasoning</dt><dd>{yesNo(model.reasoning)}</dd></div>
        <div><dt>Tool calling</dt><dd>{yesNo(model.tool_call)}</dd></div>
        <div><dt>Open weights</dt><dd>{yesNo(model.open_weights)}</dd></div>
        <div><dt>License</dt><dd>{String(model.raw.license ?? model.metadata?.license ?? 'Not reported')}</dd></div>
      </dl>
      <section className="detail-section"><h2>Azure availability</h2>
        <p><AzureSupport value={model.azure_support} /> {model.azure_support === 'listed' ? 'Listed in synced Azure sources.' : model.azure_support === 'not_listed' ? 'Not found in the synced Azure sources.' : 'Azure support has not been fully checked.'}</p>
        {model.azure_source.status === 'not_configured' ? <p>Regional availability is not checked. Seed with an Azure export or an explicitly configured subscription and regions.</p>
            : model.azure.length === 0 ? <p>No exact model ID match in the imported regions. This does not establish that the model is unavailable elsewhere.</p>
              : <div className="table-scroll" tabIndex={0} role="region" aria-label="Azure model availability">
                <table><thead><tr><th>Region</th><th>Version</th><th>Lifecycle</th><th>Deployment SKUs</th></tr></thead>
                  <tbody>{model.azure.map(item => {
                    const entries = Array.isArray(item.raw.entries) ? item.raw.entries.map(record).filter(entry => entry !== null) : []
                    return entries.map((entry, index) => {
                      const azure = record(entry.model) ?? entry
                      const skus = Array.isArray(azure.skus) ? azure.skus.map(record).filter(sku => sku !== null).map(sku => String(sku.name)) : []
                      return <tr key={`${item.location}/${item.version}/${index}`}><td>{item.location}</td>
                        <td>{item.version || 'Not reported'}</td><td>{String(azure.lifecycleStatus ?? 'Not reported')}</td><td>{skus.join(', ') || 'Not reported'}</td></tr>
                    })
                  })}</tbody></table>
              </div>}
        <p className="note">Availability is a dated, regional observation. It does not guarantee quota, capacity or permission to deploy.</p>
        {model.azure_source.status !== 'not_configured' ? <p className="note">Upstream fetched: {model.azure_source.fetched_at ? new Date(model.azure_source.fetched_at).toLocaleString() : 'Not reported'}.
          {' '}Imported: {model.azure_source.imported_at ? new Date(model.azure_source.imported_at).toLocaleString() : 'Not reported'}.</p> : null}
        {model.azure_source.locations?.length ? <p className="note">Coverage: {model.azure_source.locations.length} queried regions.</p> : null}
        {model.azure_source.unsupported_locations?.length ? <details>
          <summary>Regions without this catalogue API ({model.azure_source.unsupported_locations.length})</summary>
          <p>{model.azure_source.unsupported_locations.join(', ')}</p>
          <p className="note">These regions are listed for the subscription but are not supported by the regional model-list API. This is not an empty-model result.</p>
        </details> : null}
      </section>
      <section className="detail-section"><h2>Benchmarks</h2><Benchmarks metadata={model.metadata} /></section>
      <section className="detail-section"><h2>Provider metadata</h2>
        <p className="note">These are offerings of this model, not separate model-list entries. Prices and limits can differ by provider. The list summary uses {model.pricing_provider_id ?? 'no known Azure pricing source'}.</p>
        {model.providers.length ? <div className="table-scroll" tabIndex={0} role="region" aria-label="Provider metadata">
          <table><thead><tr><th>Provider</th><th>Provider model ID</th><th>Context</th><th>Input / 1M</th><th>Output / 1M</th></tr></thead>
            <tbody>{model.providers.map(provider => <tr key={provider.id}>
              <th scope="row">{provider.provider_name}</th><td><code>{provider.model_id}</code></td>
              <td className="numeric">{formatNumber(provider.context_tokens)}</td>
              <td className="numeric">{formatPrice(provider.input_price)}</td>
              <td className="numeric">{formatPrice(provider.output_price)}</td>
            </tr>)}</tbody></table>
        </div> : <p className="muted">No linked provider offerings were supplied for this model.</p>}
      </section>
      <section className="detail-section"><h2>Sources and full properties</h2>
        <p>Model sources: <ExternalLink href="https://models.dev">models.dev</ExternalLink> and the imported Azure catalogue. <code className="source-id">{model.model_id}</code></p>
        <p className="note">The price summary does not include every cache, batch or long-context tier. Raw properties preserve those distinctions and any conflicting upstream representations.</p>
        {Array.isArray(model.metadata?.links) ? <ul>{model.metadata.links.map(record).filter(link => link !== null).map((link, index) =>
          <li key={index}><ExternalLink href={link.url}>{String(link.label ?? link.url ?? 'Source')}</ExternalLink></li>)}</ul> : null}
        <details><summary>Summary properties and Azure price tiers</summary><pre>{JSON.stringify(model.raw, null, 2)}</pre></details>
        <details><summary>All provider properties</summary><pre>{JSON.stringify(model.providers, null, 2)}</pre></details>
        <details><summary>Model metadata and benchmark provenance</summary><pre>{JSON.stringify(model.metadata, null, 2)}</pre></details>
        {model.azure.length ? <details><summary>Azure source records</summary><pre>{JSON.stringify(model.azure, null, 2)}</pre></details> : null}
      </section>
    </> : null}
  </section>
}
