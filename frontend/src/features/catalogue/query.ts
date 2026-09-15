export function catalogueKey(query: string) {
  const params = new URLSearchParams(query)
  const values = new URLSearchParams()
  for (const key of ['q', 'azure', 'reasoning', 'sort', 'direction']) {
    const value = params.get(key)
    if (value) values.set(key, value)
  }
  values.set('offset', String(Math.max(0, Number(params.get('offset')) || 0)))
  return `/api/catalogue/models?${values}`
}
