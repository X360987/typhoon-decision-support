import { vi } from 'vitest'

type ClientModule = typeof import('../src/api/client')

/**
 * vi.mock factory: keeps the real client helpers but replaces every `api.*` call with a mock.
 * Lives apart from helpers.ts so that loading the factory never pulls in modules that import the client.
 */
export async function mockClient(importOriginal: () => Promise<ClientModule>) {
  const real = await importOriginal()
  const api: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(real.api)) api[k] = typeof v === 'function' ? vi.fn() : v
  api.exportUrl = real.api.exportUrl
  return { ...real, api }
}
