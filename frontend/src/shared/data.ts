export type Model = {
  id: string
  model_id: string
  name: string
  publisher: string | null
  azure_support: 'listed' | 'not_listed' | 'unknown'
  pricing_provider_id: string | null
  context_tokens: number | null
  output_tokens: number | null
  input_price: number | null
  output_price: number | null
  reasoning: boolean | null
  tool_call: boolean | null
  open_weights: boolean | null
}

export type ModelsPage = { items: Model[]; total: number; limit: number; offset: number }
export type ProviderOffering = {
  id: string
  provider_id: string
  provider_name: string
  model_id: string
  context_tokens: number | null
  output_tokens: number | null
  input_price: number | null
  output_price: number | null
  metadata_match: string | null
  raw: Record<string, unknown>
}
export type Status = {
  seeded_at: string | null
  model_count: number
  offering_count: number
  sources: {
    azure?: {
      status: 'not_configured' | 'file' | 'live'
      locations: string[]
      count: number
      unsupported_locations?: string[]
    }
  }
}
export type ModelDetail = Model & {
  providers: ProviderOffering[]
  raw: Record<string, unknown>
  metadata: Record<string, unknown> | null
  azure: { location: string; model_name: string; version: string; raw: Record<string, unknown> }[]
  azure_source: {
    status: 'not_configured' | 'file' | 'live'
    fetched_at?: string | null
    imported_at?: string
    locations?: string[]
    unsupported_locations?: string[]
    non_physical_locations?: string[]
  }
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) {
    let message = `The API returned HTTP ${response.status}. Check make logs and retry.`
    if (response.headers.get('content-type')?.includes('application/json')) {
      const body: unknown = await response.json()
      const detail = record(body)?.detail
      if (typeof detail === 'string') message = detail
    }
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

export function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown> : null
}

const numbers = new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 })
const prices = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 6 })
export const formatNumber = (value: number | null) => value === null ? 'Not reported' : numbers.format(value)
export const formatPrice = (value: number | null) => value === null ? 'Not reported' : prices.format(value)
export const yesNo = (value: boolean | null) => value === null ? 'Not reported' : value ? 'Yes' : 'No'

export function safeUrl(value: unknown): string | null {
  if (typeof value !== 'string' || !/^https?:\/\//i.test(value)) return null
  try {
    const url = new URL(value)
    return url.username || url.password ? null : url.href
  } catch (error) {
    if (error instanceof TypeError) return null
    throw error
  }
}
