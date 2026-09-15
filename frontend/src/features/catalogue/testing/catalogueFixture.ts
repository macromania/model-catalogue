import type { Page } from '@playwright/test'
import type { ModelDetail } from '../../../shared/data'

export async function mockCatalogue(page: Page) {
  const state = {
    models: ['Alpha', 'Beta', 'Gamma', 'Delta'].map((name, index): ModelDetail => ({
      id: `00000000-0000-0000-0000-00000000000${index + 1}`,
      name: `Fixture ${name}`, model_id: `fixture-${name.toLowerCase()}`,
      publisher: 'Fixture publisher',
      azure_support: index === 0 || index === 3 ? 'listed' : index === 1 ? 'not_listed' : 'unknown',
      pricing_provider_id: index === 0 || index === 3 ? 'azure' : null,
      context_tokens: 1000 + index, output_tokens: 100,
      input_price: index, output_price: 5, reasoning: index % 2 === 0,
      tool_call: null, open_weights: null, raw: { name, cost: { input: index } },
      metadata: null,
      providers: [{
        id: `offering-${index}`, provider_id: 'fixture', provider_name: 'Fixture provider',
        model_id: `fixture-${name.toLowerCase()}`, context_tokens: 1000, output_tokens: 100,
        input_price: index, output_price: 5, metadata_match: 'explicit fixture', raw: { name },
      }],
      azure: [], azure_source: { status: 'not_configured' },
    })),
  }
  await page.route('**/api/catalogue/status', route => route.fulfill({ json: {
    seeded_at: '2026-01-01T00:00:00Z', model_count: state.models.length, offering_count: state.models.length,
    sources: { azure: { status: 'not_configured', locations: [], count: 0 } },
  } }))
  await page.route('**/api/catalogue/models?*', route => {
    const params = new URL(route.request().url()).searchParams
    const q = (params.get('q') ?? '').toLowerCase()
    const items = state.models.filter(model =>
      (!params.get('azure') || model.azure_support === params.get('azure')) &&
      (!params.has('reasoning') || model.reasoning === (params.get('reasoning') === 'true')) &&
      `${model.name} ${model.model_id}`.toLowerCase().includes(q))
    const offset = Number(params.get('offset') ?? 0)
    return route.fulfill({ json: { items: items.slice(offset, offset + 25), total: items.length, offset, limit: 25 } })
  })
  await page.route('**/api/catalogue/models/*', route => {
    const id = new URL(route.request().url()).pathname.split('/').pop()
    const model = state.models.find(item => item.id === id)
    return model ? route.fulfill({ json: model })
      : route.fulfill({ status: 404, json: { detail: 'Fixture model no longer exists.' } })
  })
  return state
}
