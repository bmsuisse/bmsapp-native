import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  biometricConfirm,
  can,
  centerProminentEntry,
  isNativeApp,
  nativeInfo,
  on,
  setChrome,
  setWidgets,
  share,
  toast,
  type BMSNativeApi,
} from '../src/index.js'

function installBridge(overrides: Partial<BMSNativeApi> = {}) {
  const bridge = {
    platform: 'ios',
    appVersion: '1.4.0',
    webAppId: 'partner-tool',
    capabilities: ['customChrome', 'dashboardWidgets'],
    postMessage: vi.fn(),
    call: vi.fn(async () => ({ ok: true })),
    ...overrides,
  }
  window.BMSNative = bridge
  return bridge
}

afterEach(() => {
  delete window.BMSNative
  delete window.webkit
  vi.restoreAllMocks()
})

describe('in the browser (without BMSNative)', () => {
  it('detects no app and has no capabilities', () => {
    expect(isNativeApp()).toBe(false)
    expect(nativeInfo()).toBeNull()
    expect(can('camera')).toBe(false)
  })

  it('calls with a response report unavailable', async () => {
    expect(await setWidgets([])).toEqual({ ok: false, error: 'unavailable' })
  })

  it('biometricConfirm lets the web flow continue', async () => {
    expect(await biometricConfirm('Approve?')).toEqual({ ok: true })
  })

  it('share falls back to the clipboard', async () => {
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    expect(await share({ url: 'https://example.com' })).toBe('copied')
    expect(writeText).toHaveBeenCalledWith('https://example.com')
  })

  it('toast and setChrome are no-ops', () => {
    expect(() => toast('Hello')).not.toThrow()
    expect(() => setChrome({ menu: [] })).not.toThrow()
  })
})

describe('in the app (with BMSNative)', () => {
  it('reads info and capabilities', () => {
    installBridge()
    expect(isNativeApp()).toBe(true)
    expect(nativeInfo()).toEqual({
      platform: 'ios',
      appVersion: '1.4.0',
      webAppId: 'partner-tool',
      capabilities: ['customChrome', 'dashboardWidgets'],
    })
    expect(can('dashboardWidgets')).toBe(true)
    expect(can('camera')).toBe(false)
  })

  it('sends fire-and-forget messages with action', () => {
    const bridge = installBridge()
    toast('Saved', 'success')
    setChrome({ scope: 'route', actionButtons: [{ id: 'add', icon: 'plus' }] })
    expect(bridge.postMessage).toHaveBeenNthCalledWith(1, {
      action: 'toast',
      message: 'Saved',
      style: 'success',
    })
    expect(bridge.postMessage).toHaveBeenNthCalledWith(2, {
      action: 'setChrome',
      scope: 'route',
      actionButtons: [{ id: 'add', icon: 'plus' }],
    })
  })

  it('passes through the response from call', async () => {
    const bridge = installBridge({
      call: vi.fn(async () => ({ ok: true, accepted: 1, rejected: 0 })),
    })
    const res = await setWidgets([{ id: 'k', kind: 'kpi', data: { value: 1 } }])
    expect(bridge.call).toHaveBeenCalledWith('setWidgets', {
      widgets: [{ id: 'k', kind: 'kpi', data: { value: 1 } }],
    })
    expect(res).toEqual({ ok: true, accepted: 1, rejected: 0 })
  })

  it('reports an error from the app', async () => {
    installBridge({ call: vi.fn(async () => ({ ok: false, error: 'cancelled' })) })
    expect(await share({ text: 'x' })).toBe('cancelled')
  })

  it('falls back to the raw message handler on old app builds', async () => {
    const postMessage = vi.fn()
    window.webkit = { messageHandlers: { nativeBridge: { postMessage } } }
    expect(isNativeApp()).toBe(true)
    expect(await share({ url: 'https://example.com' })).toBe('shared')
    expect(postMessage).toHaveBeenCalledWith({ action: 'share', url: 'https://example.com' })
  })
})

describe('Events', () => {
  it('dispatches app callbacks to all listeners and keeps custom functions', () => {
    const own = vi.fn()
    ;(window as unknown as Record<string, unknown>).onNativeMenuSelect = own
    const a = vi.fn()
    const b = vi.fn()
    const offA = on('menuSelect', a)
    on('menuSelect', b)
    const trigger = (window as unknown as Record<string, (id: string) => void>).onNativeMenuSelect
    trigger?.('new-order')
    offA()
    trigger?.('settings')
    expect(own).toHaveBeenCalledTimes(2)
    expect(a).toHaveBeenCalledTimes(1)
    expect(b.mock.calls).toEqual([['new-order'], ['settings']])
  })
})

describe('centerProminentEntry', () => {
  it('moves the entry to the middle and marks it', () => {
    const items = [{ id: 'a' }, { id: 'b' }, { id: 'c' }, { id: 'brain' }, { id: 'd' }]
    expect(centerProminentEntry(items, 'brain').map((e) => e.id)).toEqual([
      'a',
      'b',
      'brain',
      'c',
      'd',
    ])
    expect(centerProminentEntry(items, 'brain')[2]).toEqual({ id: 'brain', prominent: true })
  })

  it('leaves the array unchanged without a matching entry', () => {
    const items = [{ id: 'a' }]
    expect(centerProminentEntry(items, 'x')).toBe(items)
  })
})
