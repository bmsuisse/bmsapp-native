import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  BACK_HANDLER_TIMEOUT_MS,
  dictate,
  getAccessToken,
  getLayout,
  keyboardHeight,
  on,
  onBackRequested,
  type LayoutInfo,
} from '../src/index.js'
import { installBridge, removeBridge } from './helpers.js'

afterEach(() => {
  vi.useRealTimers()
  removeBridge()
})

function answer(result: unknown) {
  return vi.fn(async (_action: string, _payload?: Record<string, unknown>) => result)
}

describe('dictate', () => {
  it('sends the options and returns text and locale', async () => {
    const bridge = installBridge({
      features: ['dictate'],
      call: answer({ ok: true, text: 'Zwei Paletten', locale: 'de-CH' }),
    })
    const res = await dictate({ locale: 'de-CH', maxSeconds: 30, contextualStrings: ['Palette'] })
    expect(res).toEqual({ ok: true, text: 'Zwei Paletten', locale: 'de-CH' })
    expect(bridge.call).toHaveBeenCalledWith('dictate', {
      locale: 'de-CH',
      maxSeconds: 30,
      contextualStrings: ['Palette'],
    })
    await dictate()
    expect(bridge.call).toHaveBeenLastCalledWith('dictate', {})
  })

  it.each([
    ['maxSeconds 0', { maxSeconds: 0 }],
    ['maxSeconds 121', { maxSeconds: 121 }],
    ['maxSeconds NaN', { maxSeconds: NaN }],
    ['maxSeconds a string', { maxSeconds: '30' }],
    ['51 contextual strings', { contextualStrings: Array.from({ length: 51 }, () => 'a') }],
    ['contextual string a number', { contextualStrings: [1] }],
    ['locale empty', { locale: '' }],
    ['locale a number', { locale: 5 }],
  ])('answers invalid without asking the app: %s', async (_name, options) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge({ features: ['dictate'] })
    expect(await dictate(options as never)).toMatchObject({ ok: false, error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('accepts the edges: 1 and 120 seconds, 50 strings', async () => {
    const bridge = installBridge({
      features: ['dictate'],
      call: answer({ ok: true, text: '', locale: 'de' }),
    })
    await dictate({ maxSeconds: 1 })
    await dictate({ maxSeconds: 120, contextualStrings: Array.from({ length: 50 }, () => 'a') })
    expect(bridge.call).toHaveBeenCalledTimes(2)
  })

  it.each(['cancelled', 'denied', 'unavailable', 'capability'])(
    'passes %s through',
    async (error) => {
      installBridge({ features: ['dictate'], call: answer({ ok: false, error }) })
      expect(await dictate()).toEqual({ ok: false, error })
    }
  )

  it('is unavailable outside the app, in an old app and for unknownAction', async () => {
    expect(await dictate()).toEqual({ ok: false, error: 'unavailable' })
    const bridge = installBridge()
    expect(await dictate()).toEqual({ ok: false, error: 'unavailable' })
    expect(bridge.call).not.toHaveBeenCalled()
    removeBridge()
    installBridge({ features: ['dictate'], call: answer({ ok: false, error: 'unknownAction' }) })
    expect(await dictate()).toEqual({ ok: false, error: 'unavailable' })
  })

  it('reports an answer without text as failed', async () => {
    installBridge({ features: ['dictate'], call: answer({ ok: true }) })
    expect(await dictate()).toMatchObject({ ok: false, error: 'failed' })
  })
})

const LAYOUT: LayoutInfo = {
  keyboardHeight: 336,
  keyboardVisible: true,
  sizeClass: 'regular',
  orientation: 'landscape',
  width: 1024,
  height: 420,
}

describe('getLayout and keyboardHeight', () => {
  it('returns the layout fields', async () => {
    const bridge = installBridge({ features: ['layout'], call: answer({ ok: true, ...LAYOUT }) })
    expect(await getLayout()).toEqual({ ok: true, ...LAYOUT })
    expect(bridge.call).toHaveBeenCalledWith('getLayout', {})
  })

  it('is unavailable in the browser, in an old app and for unknownAction', async () => {
    expect(await getLayout()).toEqual({ ok: false, error: 'unavailable' })
    installBridge()
    expect(await getLayout()).toEqual({ ok: false, error: 'unavailable' })
    removeBridge()
    installBridge({ features: ['layout'], call: answer({ ok: false, error: 'unknownAction' }) })
    expect(await getLayout()).toEqual({ ok: false, error: 'unavailable' })
  })

  it('reports an incomplete answer as failed', async () => {
    installBridge({ features: ['layout'], call: answer({ ok: true, keyboardHeight: 1 }) })
    expect(await getLayout()).toMatchObject({ ok: false, error: 'failed' })
  })

  it('keyboardHeight asks the app', async () => {
    installBridge({ features: ['layout'], call: answer({ ok: true, ...LAYOUT }) })
    expect(await keyboardHeight()).toBe(336)
  })

  it('keyboardHeight uses visualViewport in the browser and without the feature', async () => {
    const viewport = { height: 500, offsetTop: 0 }
    vi.stubGlobal('visualViewport', viewport)
    Object.defineProperty(window, 'visualViewport', { value: viewport, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true })
    expect(await keyboardHeight()).toBe(300)
    installBridge()
    expect(await keyboardHeight()).toBe(300)
    // The app does not answer: fall back, do not throw.
    removeBridge()
    installBridge({ features: ['layout'], call: answer({ ok: false, error: 'failed' }) })
    expect(await keyboardHeight()).toBe(300)
    viewport.height = 800
    expect(await keyboardHeight()).toBe(0)
    Object.defineProperty(window, 'visualViewport', { value: undefined, configurable: true })
    expect(await keyboardHeight()).toBe(0)
    vi.unstubAllGlobals()
  })

  it('on(layoutChange) delivers onNativeLayoutChange', () => {
    const seen: LayoutInfo[] = []
    on('layoutChange', (layout) => seen.push(layout))
    ;(window as unknown as { onNativeLayoutChange: (l: LayoutInfo) => void }).onNativeLayoutChange(
      LAYOUT
    )
    expect(seen).toEqual([LAYOUT])
  })
})

describe('onBackRequested', () => {
  type Back = (payload: { source: string }) => void
  const back = () => (window as unknown as { onNativeBackRequested?: Back }).onNativeBackRequested
  const flush = async () => {
    for (let i = 0; i < 5; i++) await Promise.resolve()
  }
  const calls = (bridge: ReturnType<typeof installBridge>) =>
    (bridge.call as unknown as { mock: { calls: [string, unknown][] } }).mock.calls.map(
      ([action, payload]) => [action, payload]
    )

  it('enables the interception, answers backResult and disables it in the cleanup', async () => {
    const bridge = installBridge({ features: ['backInterception'] })
    const handler = vi.fn(() => true)
    const off = onBackRequested(handler)
    expect(calls(bridge)).toEqual([['setBackInterception', { enabled: true }]])

    back()!({ source: 'swipe' })
    await flush()
    expect(handler).toHaveBeenCalledWith('swipe')
    expect(calls(bridge).at(-1)).toEqual(['backResult', { handled: true }])

    off()
    expect(calls(bridge).at(-1)).toEqual(['setBackInterception', { enabled: false }])
    expect(back()).toBeUndefined()
    off() // twice is harmless
    expect(bridge.call).toHaveBeenCalledTimes(3)
  })

  it('awaits an async handler and answers false for false', async () => {
    const bridge = installBridge({ features: ['backInterception'] })
    const off = onBackRequested(async (source) => {
      await Promise.resolve()
      return source === 'swipe'
    })
    back()!({ source: 'button' })
    await flush()
    expect(calls(bridge).at(-1)).toEqual(['backResult', { handled: false }])
    back()!({ source: 'swipe' })
    await flush()
    expect(calls(bridge).at(-1)).toEqual(['backResult', { handled: true }])
    off()
  })

  it('counts a handler that throws, rejects or returns something else as not handled', async () => {
    const bridge = installBridge({ features: ['backInterception'] })
    for (const handler of [
      () => {
        throw new Error('x')
      },
      () => Promise.reject(new Error('x')),
      () => 'yes' as never,
    ]) {
      const off = onBackRequested(handler)
      back()!({ source: 'button' })
      await flush()
      expect(calls(bridge).at(-1)).toEqual(['backResult', { handled: false }])
      off()
    }
  })

  it('answers false when the handler has not settled by the time limit', async () => {
    vi.useFakeTimers()
    const bridge = installBridge({ features: ['backInterception'] })
    const off = onBackRequested(() => new Promise<boolean>(() => {}))
    back()!({ source: 'button' })
    await vi.advanceTimersByTimeAsync(BACK_HANDLER_TIMEOUT_MS - 1)
    expect(calls(bridge).at(-1)).toEqual(['setBackInterception', { enabled: true }])
    await vi.advanceTimersByTimeAsync(2)
    expect(calls(bridge).at(-1)).toEqual(['backResult', { handled: false }])
    expect(BACK_HANDLER_TIMEOUT_MS).toBeLessThan(800)
    off()
  })

  it('asks the newest handler first and keeps the interception until the last one is gone', async () => {
    const bridge = installBridge({ features: ['backInterception'] })
    const page = vi.fn(() => true)
    const dialog = vi.fn(() => true)
    const offPage = onBackRequested(page)
    const offDialog = onBackRequested(dialog)
    expect(bridge.call).toHaveBeenCalledTimes(1) // enabled once
    back()!({ source: 'button' })
    await flush()
    expect(dialog).toHaveBeenCalledOnce()
    expect(page).not.toHaveBeenCalled()

    offDialog()
    expect(bridge.call).toHaveBeenCalledTimes(2) // + backResult only
    back()!({ source: 'button' })
    await flush()
    expect(page).toHaveBeenCalledOnce()
    offPage()
    expect(calls(bridge).at(-1)).toEqual(['setBackInterception', { enabled: false }])
  })

  it('passes on to the next handler when one does not handle it', async () => {
    const bridge = installBridge({ features: ['backInterception'] })
    const page = vi.fn(() => true)
    const offPage = onBackRequested(page)
    const offDialog = onBackRequested(() => false)
    back()!({ source: 'button' })
    await flush()
    expect(page).toHaveBeenCalledOnce()
    expect(calls(bridge).at(-1)).toEqual(['backResult', { handled: true }])
    offDialog()
    offPage()
  })

  it('does nothing in the browser and in an app without the feature', () => {
    const offBrowser = onBackRequested(() => true)
    expect(back()).toBeUndefined()
    offBrowser()
    const bridge = installBridge()
    const off = onBackRequested(() => true)
    off()
    expect(back()).toBeUndefined()
    expect(bridge.call).not.toHaveBeenCalled()
  })
})

describe('getAccessToken with a resource', () => {
  const resource = 'api://00000000-0000-4000-8000-000000000000/.default'

  it('sends resource and interactive and returns the token with its resource', async () => {
    const bridge = installBridge({
      features: ['tokenResources'],
      call: answer({ ok: true, token: 'a.b.c', expiresAt: 1_790_000_000, resource }),
    })
    const res = await getAccessToken({ resource, interactive: true, refresh: true })
    expect(res).toEqual({ ok: true, token: 'a.b.c', expiresAt: 1_790_000_000, resource })
    expect(bridge.call).toHaveBeenCalledWith('getAccessToken', {
      refresh: true,
      resource,
      interactive: true,
    })
    await getAccessToken({ resource })
    expect(bridge.call).toHaveBeenLastCalledWith('getAccessToken', { resource })
  })

  it('is unavailable without the feature, because an old app would ignore the resource', async () => {
    const bridge = installBridge({ capabilities: ['identity'] })
    expect(await getAccessToken({ resource })).toEqual({ ok: false, error: 'unavailable' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('does not change the call without a resource, even with interactive', async () => {
    const bridge = installBridge()
    await getAccessToken({ interactive: true })
    expect(bridge.call).toHaveBeenCalledWith('getAccessToken', {})
  })

  it.each(['forbidden', 'consentRequired', 'capability', 'notSignedIn'])(
    'passes %s through',
    async (error) => {
      installBridge({ features: ['tokenResources'], call: answer({ ok: false, error }) })
      expect(await getAccessToken({ resource })).toEqual({ ok: false, error })
    }
  )

  it('answers invalid for an empty resource or a non-boolean interactive', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge({ features: ['tokenResources'] })
    expect(await getAccessToken({ resource: '' })).toMatchObject({ error: 'invalid' })
    expect(await getAccessToken({ resource, interactive: 1 as never })).toMatchObject({
      error: 'invalid',
    })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('treats unknownAction as unavailable', async () => {
    installBridge({
      features: ['tokenResources'],
      call: answer({ ok: false, error: 'unknownAction' }),
    })
    expect(await getAccessToken({ resource })).toEqual({ ok: false, error: 'unavailable' })
  })
})
