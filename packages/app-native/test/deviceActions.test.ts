import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  addReminder,
  callPhone,
  can,
  navigate,
  saveContact,
  toDateOnly,
  toIsoWithOffset,
  type NavigatePayload,
  type SaveContactPayload,
} from '../src/index.js'
import { installBridge, removeBridge } from './helpers.js'

afterEach(removeBridge)

describe('in the app', () => {
  it('sends navigate with the payload unchanged', async () => {
    const bridge = installBridge({
      call: vi.fn(async () => ({
        ok: true,
        message: 'Route nach Müller AG in Google Maps gestartet.',
        app: 'google',
        waypoints_ignored: 'true',
      })),
    })
    const payload: NavigatePayload = {
      destination: { name: 'Müller AG', address: 'Industriestrasse 5, 4600 Olten' },
      waypoints: ['Bern', { latitude: 47.0, longitude: 7.4 }],
      mode: 'driving',
      app: 'google',
    }
    const res = await navigate(payload)
    expect(bridge.call).toHaveBeenCalledWith('navigate', payload)
    expect(res).toEqual({
      ok: true,
      message: 'Route nach Müller AG in Google Maps gestartet.',
      app: 'google',
      waypoints_ignored: 'true',
    })
  })

  it('sends the flat forms of navigate unchanged', async () => {
    const bridge = installBridge()
    await navigate({ address: 'Bahnhofstrasse 1, 8001 Zürich' })
    await navigate({ latitude: 47.37, longitude: 8.54, name: 'Zürich HB' })
    expect(bridge.call).toHaveBeenNthCalledWith(1, 'navigate', {
      address: 'Bahnhofstrasse 1, 8001 Zürich',
    })
    expect(bridge.call).toHaveBeenNthCalledWith(2, 'navigate', {
      latitude: 47.37,
      longitude: 8.54,
      name: 'Zürich HB',
    })
  })

  it('sends addReminder with confirm: false', async () => {
    const bridge = installBridge({
      call: vi.fn(async () => ({
        ok: true,
        message: 'Erinnerung angelegt.',
        list: 'Erinnerungen',
      })),
    })
    const payload = {
      title: 'Call Mr. Meier back',
      due: '2026-10-02T09:00:00+02:00',
      notes: 'Quote 4711',
      priority: 'high' as const,
      list: 'Work',
      confirm: false,
    }
    const res = await addReminder(payload)
    expect(bridge.call).toHaveBeenCalledWith('addReminder', payload)
    expect(res).toEqual({ ok: true, message: 'Erinnerung angelegt.', list: 'Erinnerungen' })
  })

  it('sends saveContact with phones, emails and address', async () => {
    const bridge = installBridge()
    const payload: SaveContactPayload = {
      givenName: 'Anna',
      organization: 'Müller AG',
      phones: ['+41 44 000 00 00', { label: 'mobile', value: '+41 79 000 00 00' }],
      emails: [{ label: 'work', value: 'anna@example.com' }],
      address: { street: 'Industriestrasse 5', postalCode: '4600', city: 'Olten', country: 'CH' },
    }
    await saveContact(payload)
    expect(bridge.call).toHaveBeenCalledWith('saveContact', payload)
  })

  it('sends callPhone', async () => {
    const bridge = installBridge()
    await callPhone({ number: '+41 44 000 00 00' })
    expect(bridge.call).toHaveBeenCalledWith('callPhone', { number: '+41 44 000 00 00' })
  })

  it('passes errors of the app through', async () => {
    installBridge({
      call: vi.fn(async () => ({
        ok: false,
        error: 'denied',
        message: 'Der Zugriff auf Erinnerungen ist nicht erlaubt.',
      })),
    })
    expect(await addReminder({ title: 'x' })).toEqual({
      ok: false,
      error: 'denied',
      message: 'Der Zugriff auf Erinnerungen ist nicht erlaubt.',
    })
  })

  it('fills in a message where the app sends none (capability)', async () => {
    installBridge({ call: vi.fn(async () => ({ ok: false, error: 'capability' })) })
    const res = await saveContact({ givenName: 'Anna' })
    expect(res.ok).toBe(false)
    expect(res.error).toBe('capability')
    expect(res.message).toMatch(/capability/i)
  })

  it('reports unknownAction from an older app without a message', async () => {
    installBridge({ call: vi.fn(async () => ({ ok: false, error: 'unknownAction' })) })
    const res = await navigate({ address: 'Bern' })
    expect(res).toMatchObject({ ok: false, error: 'unknownAction' })
    expect(res.message).toBeTruthy()
  })

  it('knows the deviceApps capability', () => {
    installBridge({ capabilities: ['deviceApps'] })
    expect(can('deviceApps')).toBe(true)
  })
})

describe('outside the app', () => {
  it('addReminder and saveContact are unavailable', async () => {
    for (const res of [await addReminder({ title: 'x' }), await saveContact({ givenName: 'A' })]) {
      expect(res).toMatchObject({ ok: false, error: 'unavailable' })
      expect(res.message).toBeTruthy()
    }
  })

  it('navigate opens a Google Maps route in a new tab', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    const res = await navigate({ destination: 'Bahnhofstrasse 1, 8001 Zürich' })
    expect(res).toMatchObject({ ok: true, app: 'google' })
    expect(open).toHaveBeenCalledTimes(1)
    const [url, target, features] = open.mock.calls[0] as [string, string, string]
    const parsed = new URL(url)
    expect(`${parsed.origin}${parsed.pathname}`).toBe('https://www.google.com/maps/dir/')
    expect(parsed.searchParams.get('api')).toBe('1')
    expect(parsed.searchParams.get('destination')).toBe('Bahnhofstrasse 1, 8001 Zürich')
    expect([target, features]).toEqual(['_blank', 'noopener'])
  })

  it('navigate prefers coordinates, keeps stops and maps the travel mode', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    await navigate({
      destination: { address: 'ignored', latitude: 47.37, longitude: 8.54 },
      waypoints: ['Olten', { address: 'Bern' }, { name: '' }],
      mode: 'cycling',
    })
    const parsed = new URL(open.mock.calls[0]![0] as string)
    expect(parsed.searchParams.get('destination')).toBe('47.37,8.54')
    expect(parsed.searchParams.get('waypoints')).toBe('Olten|Bern')
    expect(parsed.searchParams.get('travelmode')).toBe('bicycling')
  })

  it('navigate understands the flat forms', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    await navigate({ address: 'Bern' })
    await navigate({ latitude: 46.95, longitude: 7.45, name: 'Bern' })
    expect(new URL(open.mock.calls[0]![0] as string).searchParams.get('destination')).toBe('Bern')
    expect(new URL(open.mock.calls[1]![0] as string).searchParams.get('destination')).toBe(
      '46.95,7.45'
    )
  })

  it('navigate treats a place with only a name as invalid, like the app', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    expect(await navigate({ destination: { name: 'Müller AG' } })).toMatchObject({
      ok: false,
      error: 'invalid',
    })
    expect(open).not.toHaveBeenCalled()

    // A stop with only a name is dropped, the route itself stays.
    await navigate({ destination: 'Bern', waypoints: [{ name: 'Müller AG' }, 'Olten'] })
    const stops = new URL(open.mock.calls[0]![0] as string).searchParams.get('waypoints')
    expect(stops).toBe('Olten')
  })

  it('navigate without a usable destination is invalid and opens nothing', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    expect(await navigate({ destination: '  ' })).toMatchObject({ ok: false, error: 'invalid' })
    expect(await navigate({ destination: { latitude: 200, longitude: 8 } })).toMatchObject({
      ok: false,
      error: 'invalid',
    })
    expect(open).not.toHaveBeenCalled()
  })

  it('callPhone opens a tel: link with only digits and a leading plus', async () => {
    const hrefs: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement
    ) {
      hrefs.push(this.getAttribute('href') ?? '')
    })
    const res = await callPhone({ number: ' +41 (44) 000-00 00 ' })
    expect(res).toMatchObject({ ok: true })
    expect(hrefs).toEqual(['tel:+41440000000'])
    expect(document.querySelector('a[href^="tel:"]')).toBeNull()
  })

  it('callPhone with no digits is invalid', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    expect(await callPhone({ number: 'call me' })).toMatchObject({ ok: false, error: 'invalid' })
    expect(click).not.toHaveBeenCalled()
  })
})

describe('dates', () => {
  it('toIsoWithOffset writes the local time with its offset', () => {
    vi.stubEnv('TZ', 'Europe/Zurich')
    expect(toIsoWithOffset(new Date(2026, 9, 2, 9, 0, 0))).toBe('2026-10-02T09:00:00+02:00')
    expect(toIsoWithOffset(new Date(2026, 0, 15, 17, 5, 9))).toBe('2026-01-15T17:05:09+01:00')
  })

  it('toIsoWithOffset handles negative and half-hour offsets', () => {
    vi.stubEnv('TZ', 'America/New_York')
    expect(toIsoWithOffset(new Date(2026, 0, 15, 8, 30, 0))).toBe('2026-01-15T08:30:00-05:00')
    vi.stubEnv('TZ', 'Asia/Kolkata')
    expect(toIsoWithOffset(new Date(2026, 9, 2, 9, 0, 0))).toBe('2026-10-02T09:00:00+05:30')
    vi.stubEnv('TZ', 'UTC')
    expect(toIsoWithOffset(new Date(Date.UTC(2026, 9, 2, 9, 0, 0)))).toBe(
      '2026-10-02T09:00:00+00:00'
    )
  })

  it('toIsoWithOffset describes the same moment as the Date', () => {
    vi.stubEnv('TZ', 'Europe/Zurich')
    const date = new Date(2026, 9, 2, 9, 0, 0)
    expect(new Date(toIsoWithOffset(date)).getTime()).toBe(date.getTime())
  })

  it('toDateOnly is the local date, not the UTC date', () => {
    vi.stubEnv('TZ', 'Europe/Zurich')
    const earlyMorning = new Date(2026, 9, 2, 0, 30)
    expect(earlyMorning.toISOString().slice(0, 10)).toBe('2026-10-01') // the trap
    expect(toDateOnly(earlyMorning)).toBe('2026-10-02')
  })

  it('reject an invalid date', () => {
    expect(() => toIsoWithOffset(new Date('nope'))).toThrow(RangeError)
    expect(() => toDateOnly(new Date('nope'))).toThrow(RangeError)
  })
})

describe('types', () => {
  it('requires a name or a company for contacts', () => {
    // @ts-expect-error neither givenName, familyName nor organization
    const _noName: SaveContactPayload = { phones: ['+41 44 000 00 00'] }
    const _byOrganization: SaveContactPayload = { organization: 'Müller AG' }
    const _byFamilyName: SaveContactPayload = { familyName: 'Muster', confirm: false }
    expect([_noName, _byOrganization, _byFamilyName]).toHaveLength(3)
  })

  it('requires a destination for navigate', () => {
    // @ts-expect-error no destination
    const _nothing: NavigatePayload = { mode: 'walking' }
    expect(_nothing).toBeDefined()
  })
})
