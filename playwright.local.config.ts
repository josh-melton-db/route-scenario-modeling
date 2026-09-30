import { defineConfig } from '@playwright/test'

// Uses only the already-running app; never starts or stops local servers.
export default defineConfig({
  testDir: './e2e',
  workers: 1,
  timeout: 60_000,
  use: { baseURL: 'http://localhost:5180', trace: 'retain-on-failure' },
})
