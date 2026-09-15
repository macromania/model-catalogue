import { test, expect } from '@playwright/test'
import type { ModelsPage } from '../../shared/data'
import { mockCatalogue } from './testing/catalogueFixture'

test('real database catalogue, filtering and model detail', async ({ page, request }) => {
  const response = await request.get('/api/catalogue/models?limit=1')
  expect(response.ok()).toBe(true)
  const data: ModelsPage = await response.json()
  const model = data.items[0]
  expect(model).toBeDefined()
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Models', exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Model catalogue results' })).toBeVisible()
  const search = model.model_id.slice(0, 100)
  await page.getByLabel('Search models').fill(search)
  await expect(page.getByRole('combobox', { name: 'Provider', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Apply filters' }).click()
  expect(new URL(page.url()).searchParams.get('q')).toBe(search)
  await page.getByRole('button', { name: model.name, exact: true }).first().click()
  await expect(page.getByRole('heading', { name: model.name, exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Azure availability' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Benchmarks', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Provider metadata' })).toBeVisible()
  await page.getByText('Summary properties and Azure price tiers', { exact: true }).click()
  await expect(page.locator('details[open] pre')).toContainText('name')
  await page.getByRole('button', { name: 'Back to catalogue' }).click()
  await expect(page.getByLabel('Search models')).toHaveValue(search)
  expect(errors).toEqual([])
})

test('empty search results are explicit', async ({ page }) => {
  await mockCatalogue(page)
  await page.goto('/?q=absent-from-controlled-fixture')
  await expect(page.getByRole('status').filter({ hasText: 'No models match' })).toBeVisible()
})

test('narrow layout and bookmarked Azure support', async ({ page, request }) => {
  const response = await request.get('/api/catalogue/models?limit=1')
  const data: ModelsPage = await response.json()
  const support = data.items[0].azure_support
  await page.goto(`/?azure=${support}`)
  await expect(page.getByRole('region', { name: 'Model catalogue results' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Azure support', exact: true })).toHaveValue(support)
  await expect(page.getByRole('columnheader', { name: 'Provider', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/catalogue-${test.info().project.name}.png`, fullPage: true })
})

test('API failures produce a useful retry state', async ({ page }) => {
  await page.route('**/api/catalogue/models?*', route => route.fulfill({
    status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Database unavailable for this test.' }),
  }))
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('Database unavailable')
  await expect(page.getByRole('button', { name: 'Retry models' })).toBeVisible()
})

test('out-of-range pages preserve filters when returning to page one', async ({ page }) => {
  await mockCatalogue(page)
  await page.goto('/?azure=listed&offset=1000000')
  await page.getByRole('button', { name: 'Go to first page' }).click()
  expect(new URL(page.url()).searchParams.get('azure')).toBe('listed')
  expect(new URL(page.url()).searchParams.has('offset')).toBe(false)
  await expect(page.getByRole('button', { name: 'Fixture Alpha', exact: true })).toBeVisible()
})

test('negative reasoning filters remain visible and keyboard focus survives submit', async ({ page }) => {
  await mockCatalogue(page)
  await page.goto('/?reasoning=false')
  await expect(page.getByRole('combobox', { name: 'Reasoning', exact: true })).toHaveValue('false')
  const search = page.getByLabel('Search models')
  await search.fill('Beta')
  await search.press('Enter')
  await expect(search).toBeFocused()
  expect(new URL(page.url()).searchParams.get('reasoning')).toBe('false')
  await expect(page.getByRole('button', { name: 'Fixture Beta', exact: true })).toBeVisible()
  await page.goBack()
  await expect(search).toHaveValue('')
  await expect(page.getByRole('combobox', { name: 'Reasoning', exact: true })).toHaveValue('false')
})

test('failed metadata does not claim an empty database', async ({ page }) => {
  await mockCatalogue(page)
  await page.route('**/api/catalogue/status', route => route.fulfill({ status: 503, json: { detail: 'Metadata unavailable.' } }))
  await page.goto('/?q=not-in-fixture')
  await expect(page.getByText('Snapshot metadata unavailable', { exact: true })).toBeVisible()
  await expect(page.getByText('Snapshot metadata is not available yet', { exact: false })).toBeVisible()
  await expect(page.getByText('No seeded snapshot', { exact: true })).toHaveCount(0)
  await expect(page.getByText('The database is empty.', { exact: false })).toHaveCount(0)
})

test('pending metadata stays explicitly pending', async ({ page }) => {
  await mockCatalogue(page)
  let release = () => {}
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/catalogue/status', async route => {
    await gate
    await route.fulfill({ json: { seeded_at: null, model_count: 0, offering_count: 0, sources: {} } })
  })

  try {
    await page.goto('/')
    await expect(page.getByRole('button', { name: 'Fixture Alpha', exact: true })).toBeVisible()
    await expect(page.getByText('Loading snapshot metadata...', { exact: true })).toBeVisible()
    await expect(page.getByText('No seeded snapshot', { exact: true })).toHaveCount(0)
  } finally { release() }
})

test('Azure support indicators have evidence-aware accessible labels', async ({ page }) => {
  await mockCatalogue(page)
  await page.goto('/')
  await expect(page.getByRole('img', { name: 'Listed in Azure', exact: true })).toHaveCount(2)
  await expect(page.getByRole('img', { name: 'Not found in synced Azure sources', exact: true })).toHaveCount(1)
  await expect(page.getByRole('img', { name: 'Azure support not fully checked', exact: true })).toHaveCount(1)
})
