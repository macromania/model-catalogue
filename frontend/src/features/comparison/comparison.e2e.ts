import { test, expect } from '@playwright/test'
import { mockCatalogue } from '../catalogue/testing/catalogueFixture'

test('comparison limit, individual off-page removal and clear', async ({ page }) => {
  await mockCatalogue(page)
  await page.goto('/')
  const checkboxes = page.getByRole('region', { name: 'Model catalogue results' }).getByRole('checkbox')
  await checkboxes.nth(0).check()
  await checkboxes.nth(1).check()
  await checkboxes.nth(2).check()
  await expect(checkboxes.nth(3)).toBeDisabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/comparison-${test.info().project.name}.png`, fullPage: true })
  await page.getByLabel('Search models').fill('Delta')
  await page.getByRole('button', { name: 'Apply filters' }).click()
  await page.getByRole('button', { name: 'Remove fixture-alpha from comparison' }).click()
  await expect(page.getByRole('heading', { name: 'Compare (2/3)' })).toBeVisible()
  await expect(checkboxes.first()).toBeEnabled()
  await page.getByRole('button', { name: 'Clear comparison' }).click()
  await expect(page.getByRole('region', { name: 'Model comparison' })).toHaveCount(0)
})

test('failed refresh preserves choices without an unhandled rejection', async ({ page }) => {
  await mockCatalogue(page)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await page.getByRole('checkbox', { name: 'Compare Fixture Alpha' }).check()
  await page.route('**/api/catalogue/status', route => route.fulfill({ status: 503, json: { detail: 'Refresh failed for this test.' } }))
  await page.getByRole('button', { name: 'Refresh view' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Refresh failed for this test.' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Compare (1/3)' })).toBeVisible()
  expect(errors).toEqual([])
})

test('successful refresh updates selected records and reports removed models', async ({ page }) => {
  const state = await mockCatalogue(page)
  await page.goto('/')
  await page.getByRole('checkbox', { name: 'Compare Fixture Alpha' }).check()
  await page.getByRole('checkbox', { name: 'Compare Fixture Beta' }).check()
  state.models[0].input_price = 9.25
  state.models.splice(1, 1)
  await page.getByRole('button', { name: 'Refresh view' }).click()
  await expect(page.getByRole('heading', { name: 'Compare (1/3)' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Model comparison' })).toContainText('$9.25')
  await expect(page.getByRole('status').filter({ hasText: 'no longer in this snapshot' })).toBeVisible()
})
