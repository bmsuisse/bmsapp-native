import { vi } from 'vitest'
import type { BMSNativeApi } from '../src/index.js'

/** Sets up `window.BMSNative` like the app does, with mocks for both calls. */
export function installBridge(overrides: Partial<BMSNativeApi> = {}) {
  const bridge = {
    platform: 'ios',
    appVersion: '1.4.0',
    webAppId: 'partner-tool',
    capabilities: ['identity', 'deviceApps'],
    postMessage: vi.fn(),
    call: vi.fn(async (_action: string, _payload?: Record<string, unknown>) => ({ ok: true })),
    ...overrides,
  }
  window.BMSNative = bridge
  return bridge
}

/** Back to a regular browser. */
export function removeBridge() {
  delete window.BMSNative
  delete window.webkit
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
}
