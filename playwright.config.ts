import { defineConfig } from '@playwright/test'

const backendPort = 8931
const frontendPort = 5179

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: `http://localhost:${frontendPort}`,
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `env PYTHONPATH=. DATA_BACKEND=stub .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port ${backendPort}`,
      url: `http://127.0.0.1:${backendPort}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --port ${frontendPort} --strictPort`,
      url: `http://localhost:${frontendPort}/`,
      env: { API_PROXY_TARGET: `http://127.0.0.1:${backendPort}` },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
