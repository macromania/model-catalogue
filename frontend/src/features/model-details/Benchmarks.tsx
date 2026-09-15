import { formatNumber, record, safeUrl } from '../../shared/data'
import { ExternalLink } from '../../shared/ui'

export function Benchmarks({ metadata }: { metadata: Record<string, unknown> | null }) {
  const benchmarks = Array.isArray(metadata?.benchmarks) ? metadata.benchmarks.map(record).filter(row => row !== null) : []
  if (!benchmarks.length) return <p className="muted">No structured benchmarks were supplied for this model.</p>
  return <>
    <p className="note">Reported results, not local measurements. Different versions, harnesses and tool settings are not directly comparable.</p>
    <div className="table-scroll" tabIndex={0} role="region" aria-label="Benchmark results">
      <table><thead><tr><th>Benchmark</th><th>Score</th><th>Configuration</th><th>Source</th></tr></thead>
        <tbody>{benchmarks.map((row, index) => <tr key={index}>
          <th scope="row">{String(row.name ?? 'Unnamed benchmark')}</th>
          <td className="numeric">{typeof row.score === 'number' ? formatNumber(row.score) : 'Not reported'}
            <small>{typeof row.metric === 'string' ? row.metric : 'Unit not supplied'}</small></td>
          <td>{['version', 'variant', 'harness', 'dataset'].filter(key => row[key] !== undefined && row[key] !== null && row[key] !== '')
            .map(key => <small key={key}>{key}: {String(row[key])}</small>)}
            {['version', 'variant', 'harness', 'dataset'].every(key => row[key] === undefined || row[key] === null || row[key] === '') ? 'Not reported' : null}</td>
          <td>{safeUrl(row.source) ? <ExternalLink href={row.source}>Result source</ExternalLink> : 'Not reported'}
            {typeof row.date === 'string' ? <small>{row.date}</small> : null}</td>
        </tr>)}</tbody></table>
    </div>
  </>
}
