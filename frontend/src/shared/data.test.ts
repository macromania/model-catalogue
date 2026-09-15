import { describe, expect, it } from 'vitest'
import { formatNumber, formatPrice, safeUrl, yesNo } from './data'

describe('honest value formatting', () => {
  it('distinguishes unknown values from zero and false', () => {
    expect(formatNumber(null)).toBe('Not reported')
    expect(formatNumber(0)).toBe('0')
    expect(formatPrice(0)).toBe('$0.00')
    expect(formatPrice(null)).toBe('Not reported')
    expect(yesNo(null)).toBe('Not reported')
    expect(yesNo(false)).toBe('No')
  })
  it('only renders credential-free http and https source links', () => {
    expect(safeUrl('https://models.dev')).toBe('https://models.dev/')
    expect(safeUrl('javascript:alert(1)')).toBeNull()
    expect(safeUrl('https://user:password@example.com')).toBeNull()
    expect(safeUrl('https://')).toBeNull()
    expect(safeUrl(null)).toBeNull()
  })
})
