import type { ReactNode } from 'react'
import { formatNumber, formatPrice, yesNo } from '../../shared/data'
import type { Model } from '../../shared/data'
import { AzureSupport } from '../../shared/AzureSupport'
import './comparison.css'

export function Comparison({ models, clear, remove }: { models: Model[]; clear: () => void; remove: (id: string) => void }) {
  if (models.length === 0) return null
  const rows: [string, (model: Model) => ReactNode][] = [
    ['Azure support', model => <AzureSupport value={model.azure_support} />],
    ['Context tokens', model => formatNumber(model.context_tokens)],
    ['Output tokens', model => formatNumber(model.output_tokens)],
    ['Azure input / 1M tokens', model => formatPrice(model.input_price)],
    ['Azure output / 1M tokens', model => formatPrice(model.output_price)],
    ['Reasoning', model => yesNo(model.reasoning)],
    ['Tool calling', model => yesNo(model.tool_call)],
    ['Open weights', model => yesNo(model.open_weights)],
  ]
  return <section className="comparison" aria-labelledby="comparison-title">
    <div className="section-heading"><h2 id="comparison-title">Compare ({models.length}/3)</h2>
      <button onClick={clear}>Clear comparison</button></div>
    <div className="table-scroll" tabIndex={0} role="region" aria-label="Model comparison">
      <table><thead><tr><th scope="col">Property</th>{models.map(model =>
        <th scope="col" key={model.id}>{model.name}<small>{model.model_id}</small>
          <button onClick={() => remove(model.id)} aria-label={`Remove ${model.model_id} from comparison`}>Remove</button></th>,
      )}</tr></thead><tbody>{rows.map(([label, render]) =>
        <tr key={label}><th scope="row">{label}</th>{models.map(model =>
          <td key={model.id}>{render(model)}</td>)}</tr>,
      )}</tbody></table>
    </div>
    <p className="note">Prices are reported Azure base rates in USD. Check each model for context tiers and provider metadata.</p>
  </section>
}
