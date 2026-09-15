import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { Benchmarks } from './Benchmarks'

it('renders null provenance and invalid source links as unknown', () => {
  const html = renderToStaticMarkup(createElement(Benchmarks, {
    metadata: { benchmarks: [{
      name: 'Fixture benchmark', score: 12, version: null, variant: null,
      harness: null, dataset: null, source: 'javascript:alert(1)',
    }] },
  }))
  expect(html).not.toContain('version: null')
  expect(html).not.toContain('Result source')
  expect(html).not.toContain('javascript:')
  expect(html.match(/Not reported/g)?.length).toBe(2)
})
