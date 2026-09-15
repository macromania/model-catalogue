import type { Model } from './data'

export function AzureSupport({ value }: { value: Model['azure_support'] }) {
  const label = value === 'listed' ? 'Listed in Azure' : value === 'not_listed'
    ? 'Not found in synced Azure sources' : 'Azure support not fully checked'
  return <span className={`azure-support ${value}`} role="img" aria-label={label} title={`${label}. This does not guarantee quota or permission to deploy.`}>
    {value === 'listed' ? <>&#10003;</> : value === 'not_listed' ? <>&#10005;</> : '?'}
  </span>
}
