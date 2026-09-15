import { defineConfig } from '@playwright/test'
import { hostPorts } from './ports.ts'

export default defineConfig({
  testDir: './src/features',
  testMatch: '**/*.e2e.ts',
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: process.env.CATALOGUE_BASE_URL ?? `http://127.0.0.1:${hostPorts().ui}`,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
})
