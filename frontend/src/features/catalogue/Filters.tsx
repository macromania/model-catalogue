import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { navigate } from '../../shared/navigation'

function valuesFromQuery(query: string) {
  const params = new URLSearchParams(query)
  return {
    q: params.get('q') ?? '', azure: params.get('azure') ?? '',
    sort: params.get('sort') ?? 'name', direction: params.get('direction') ?? 'asc',
    reasoning: params.get('reasoning') ?? '',
  }
}

export function Filters({ query }: { query: string }) {
  const [values, setValues] = useState(() => valuesFromQuery(query))

  useEffect(() => {
    const restore = () => setValues(valuesFromQuery(window.location.search))
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [])

  function update(key: keyof typeof values, value: string) {
    setValues(current => ({ ...current, [key]: value }))
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const values = new FormData(event.currentTarget)
    const next = new URLSearchParams()
    for (const key of ['q', 'azure', 'reasoning', 'sort', 'direction']) {
      const value = values.get(key)
      if (typeof value === 'string' && value.trim()) next.set(key, value.trim())
    }
    navigate(next)
  }

  return <form className="filters" onSubmit={submit}>
    <label className="search">Search models<input name="q" type="search" placeholder="Name, model ID or publisher" maxLength={200} value={values.q} onChange={event => update('q', event.target.value)} /></label>
    <label><span id="azure-label">Azure support</span><select name="azure" aria-labelledby="azure-label" value={values.azure} onChange={event => update('azure', event.target.value)}>
      <option value="">Any</option><option value="listed">Listed</option><option value="not_listed">Not listed</option><option value="unknown">Not checked</option>
    </select></label>
    <label><span id="sort-label">Sort by</span><select name="sort" aria-labelledby="sort-label" value={values.sort} onChange={event => update('sort', event.target.value)}>
      <option value="name">Name</option><option value="context">Context window</option><option value="input_price">Azure input price</option><option value="output_price">Azure output price</option></select></label>
    <label><span id="order-label">Order</span><select name="direction" aria-labelledby="order-label" value={values.direction} onChange={event => update('direction', event.target.value)}><option value="asc">Ascending</option><option value="desc">Descending</option></select></label>
    <label><span id="reasoning-label">Reasoning</span><select name="reasoning" aria-labelledby="reasoning-label" value={values.reasoning} onChange={event => update('reasoning', event.target.value)}>
      <option value="">Any</option><option value="true">Yes</option><option value="false">No</option></select></label>
    <button type="submit" className="primary">Apply filters</button>
    <button type="button" onClick={() => navigate(new URLSearchParams())}>Reset</button>
  </form>
}
