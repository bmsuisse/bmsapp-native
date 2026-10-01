import { afterEach, describe, expect, it, vi } from 'vitest'
import { can, getAccessToken } from '../src/index.js'
import { installBridge, removeBridge } from './helpers.js'

afterEach(removeBridge)

describe('getAccessToken', () => {
  it('asks the app for the token without extra fields by default', async () => {
    const bridge = installBridge({
      call: vi.fn(async () => ({ ok: true, token: 'a.b.c', expiresAt: 1_790_000_000 })),
    })
    const res = await getAccessToken()
    expect(bridge.call).toHaveBeenCalledWith('getAccessToken', {})
    expect(res).toEqual({ ok: true, token: 'a.b.c', expiresAt: 1_790_000_000 })
  })

  it('passes refresh through to force a new token', async () => {
    const bridge = installBridge()
    await getAccessToken({ refresh: true })
    expect(bridge.call).toHaveBeenCalledWith('getAccessToken', { refresh: true })
  })

  it('does not send refresh: false', async () => {
    const bridge = installBridge()
    await getAccessToken({ refresh: false })
    expect(bridge.call).toHaveBeenCalledWith('getAccessToken', {})
  })

  it.each(['capability', 'forbidden', 'notSignedIn'])('reports the app error %s', async (error) => {
    installBridge({ call: vi.fn(async () => ({ ok: false, error })) })
    expect(await getAccessToken()).toEqual({ ok: false, error })
  })

  it('narrows the type: token and expiresAt exist when ok', async () => {
    installBridge({
      call: vi.fn(async () => ({ ok: true, token: 'a.b.c', expiresAt: 1_790_000_000 })),
    })
    const res = await getAccessToken()
    if (res.ok) {
      const token: string = res.token
      const seconds: number = res.expiresAt
      expect([token, seconds]).toEqual(['a.b.c', 1_790_000_000])
    } else {
      expect.unreachable()
    }
  })

  it('knows the identity capability', () => {
    installBridge({ capabilities: ['identity'] })
    expect(can('identity')).toBe(true)
    expect(can('deviceApps')).toBe(false)
  })

  it('is unavailable outside the app', async () => {
    expect(await getAccessToken()).toEqual({ ok: false, error: 'unavailable' })
    expect(await getAccessToken({ refresh: true })).toEqual({ ok: false, error: 'unavailable' })
  })
})
