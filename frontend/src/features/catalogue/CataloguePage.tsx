import type { Dispatch, SetStateAction } from 'react'
import useSWR from 'swr'
import { fetchJson, formatNumber, formatPrice } from '../../shared/data'
import type { Model, ModelsPage, Status } from '../../shared/data'
import { AzureSupport } from '../../shared/AzureSupport'
import { Feedback, Loading } from '../../shared/ui'
import { changeParameter } from '../../shared/navigation'
import { Comparison } from '../comparison/Comparison'
import { Filters } from './Filters'
import { catalogueKey } from './query'
import './catalogue.css'

type Props = {
  query: string
  status?: Status
  selected: Model[]
  setSelected: Dispatch<SetStateAction<Model[]>>
}

export function CataloguePage({ query, status, selected, setSelected }: Props) {
  const params = new URLSearchParams(query)
  const offset = Math.max(0, Number(params.get('offset')) || 0)
  const { data: page, error, isLoading, mutate } = useSWR<ModelsPage>(catalogueKey(query), fetchJson)

  return <>
    <h1>Models</h1>
    <p className="intro">One row per model. Check Azure support, compare Azure prices, and inspect provider metadata in the details.</p>
    <Filters query={query} />
    <Comparison models={selected} clear={() => setSelected([])} remove={id => setSelected(current => current.filter(model => model.id !== id))} />
    {isLoading ? <Loading /> : error ? <Feedback error>{error.message} <button onClick={() => void mutate(undefined, { revalidate: true, populateCache: false, throwOnError: false })}>Retry models</button></Feedback>
      : page && page.items.length === 0 ? <Feedback>{page.total > 0
        ? <>This page is outside the current results. <button onClick={() => changeParameter(query, 'offset', null)}>Go to first page</button></>
        : status === undefined
          ? <>No models were returned. Snapshot metadata is not available yet; refresh the view to confirm whether a seed is needed.</>
          : status.seeded_at
            ? <>No models match these filters. Change the search or reset the filters.</>
            : <>The database is empty. Run <code>make seed</code>, then select Refresh view.</>}</Feedback>
          : page ? <>
            <div className="results-heading"><p role="status">{formatNumber(page.total)} matching {page.total === 1 ? 'model' : 'models'}</p><p>Select up to 3 to compare.</p></div>
            <div className="table-scroll" tabIndex={0} role="region" aria-label="Model catalogue results">
              <table><thead><tr><th scope="col">Compare</th><th scope="col">Model</th><th scope="col">Azure</th><th scope="col">Context</th><th scope="col">Output limit</th><th scope="col">Azure input / 1M</th><th scope="col">Azure output / 1M</th></tr></thead>
                <tbody>{page.items.map(model => {
                  const checked = selected.some(item => item.id === model.id)
                  return <tr key={model.id} className={checked ? 'selected' : undefined}>
                    <td className="compare-cell"><label className="compare-toggle"><input aria-label={`Compare ${model.name}`} type="checkbox" checked={checked} disabled={!checked && selected.length === 3}
                      onChange={() => setSelected(current => checked ? current.filter(item => item.id !== model.id) : [...current, model])} /></label></td>
                    <th scope="row"><button className="model-link" onClick={() => changeParameter(query, 'model', model.id)}>{model.name}</button><small>{model.model_id}</small></th>
                    <td><AzureSupport value={model.azure_support} /></td><td className="numeric">{formatNumber(model.context_tokens)}</td><td className="numeric">{formatNumber(model.output_tokens)}</td>
                    <td className="numeric">{formatPrice(model.input_price)}</td><td className="numeric">{formatPrice(model.output_price)}</td>
                  </tr>
                })}</tbody></table>
            </div>
            <nav className="pagination" aria-label="Results pages"><button disabled={offset === 0} onClick={() => changeParameter(query, 'offset', String(Math.max(0, offset - page.limit)))}>Previous</button>
              <span>{formatNumber(offset + 1)} to {formatNumber(Math.min(offset + page.limit, page.total))} of {formatNumber(page.total)}</span>
              <button disabled={offset + page.limit >= page.total} onClick={() => changeParameter(query, 'offset', String(offset + page.limit))}>Next</button></nav>
          </> : null}
    <p className="note">Azure ticks reflect synced listings, not deployment eligibility. Limits prefer an Azure listing where known; otherwise they use canonical metadata. Prices are Azure base USD rates, not billing quotes. Provider-specific rates remain in the details.</p>
  </>
}
