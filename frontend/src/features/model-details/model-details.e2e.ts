import { test, expect } from '@playwright/test'
import { mockCatalogue } from '../catalogue/testing/catalogueFixture'

test('model details retain providers and distinguish listing from verified availability', async ({ page }) => {
  const state = await mockCatalogue(page)
  state.models[0].providers[0].provider_id = 'azure-cognitive-services'
  state.models[0].providers[0].provider_name = 'Azure Cognitive Services'
  await page.goto(`/?model=${state.models[0].id}`)
  await expect(page.getByText('Regional availability is not checked.', { exact: false })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Provider metadata' })).toContainText('Azure Cognitive Services')
  await expect(page.getByRole('img', { name: 'Listed in Azure' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/model-details-${test.info().project.name}.png`, fullPage: true })
})
