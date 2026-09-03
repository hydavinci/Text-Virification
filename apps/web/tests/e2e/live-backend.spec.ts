import { expect, test } from '@playwright/test'

const liveApiUrl = (
  globalThis as typeof globalThis & {
    process?: { env?: Record<string, string | undefined> }
  }
).process?.env?.LIVE_API_URL

test('live backend boundary exposes the real API health endpoint', async ({
  request
}) => {
  test.skip(
    !liveApiUrl,
    'LIVE_API_URL is not set; deterministic route fixtures do not validate backend internals.'
  )

  const response = await request.get(`${liveApiUrl}/api/v1/health`)
  expect(response.ok()).toBe(true)
})
