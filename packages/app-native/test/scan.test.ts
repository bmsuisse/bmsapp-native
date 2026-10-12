import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  BARCODE_FORMATS,
  canScan,
  on,
  scanBarcode,
  scanBarcodes,
  scanText,
  SCAN_LIMITS,
} from '../src/index.js'
import { installBridge, removeBridge } from './helpers.js'

afterEach(removeBridge)

describe('canScan', () => {
  it('needs the camera capability', () => {
    expect(canScan()).toBe(false)
    installBridge({ capabilities: ['deviceApps'] })
    expect(canScan()).toBe(false)
    installBridge({ capabilities: ['camera'] })
    expect(canScan()).toBe(true)
  })
})

describe('scanText', () => {
  it('sends the pattern and returns the text', async () => {
    const bridge = installBridge({ call: vi.fn(async () => ({ ok: true, text: 'AB-1234' })) })
    const res = await scanText({ pattern: '[A-Z]{2}-\\d{4,}' })
    expect(bridge.call).toHaveBeenCalledWith('scanText', { pattern: '[A-Z]{2}-\\d{4,}' })
    expect(res).toEqual({ ok: true, text: 'AB-1234' })
  })

  it('sends no pattern for none, null or an empty string', async () => {
    const call = vi.fn(async (_action: string, _payload?: Record<string, unknown>) => ({
      ok: true,
      text: 'x',
    }))
    installBridge({ call })
    await scanText()
    await scanText({ pattern: null })
    await scanText({ pattern: '' })
    expect(call.mock.calls).toEqual([
      ['scanText', {}],
      ['scanText', {}],
      ['scanText', {}],
    ])
  })

  it('sends the source of a RegExp without its i flag and warns about other flags', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge({ call: vi.fn(async () => ({ ok: true, text: 'x' })) })
    await scanText({ pattern: /\d{4}/i })
    expect(bridge.call).toHaveBeenLastCalledWith('scanText', { pattern: '\\d{4}' })
    expect(warn).not.toHaveBeenCalled()
    await scanText({ pattern: /\d{4}/g })
    expect(warn).toHaveBeenCalledOnce()
    expect(warn.mock.calls[0]?.[0]).toContain('"g"')
  })

  it('warns about a long pattern and JavaScript-only syntax, but still sends it', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge({ call: vi.fn(async () => ({ ok: true, text: 'x' })) })
    const long = 'a'.repeat(SCAN_LIMITS.patternLength + 1)
    await scanText({ pattern: long })
    expect(bridge.call).toHaveBeenLastCalledWith('scanText', { pattern: long })
    await scanText({ pattern: '(?<=A)\\d+' })
    expect(warn).toHaveBeenCalledTimes(2)
  })

  it('does not warn in a production bundle', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    installBridge({ call: vi.fn(async () => ({ ok: true, text: 'x' })) })
    await scanText({ pattern: 'a'.repeat(300) })
    expect(warn).not.toHaveBeenCalled()
  })

  it.each(['invalid', 'capability', 'denied', 'cancelled', 'busy', 'unavailable'] as const)(
    'passes %s through',
    async (error) => {
      installBridge({ call: vi.fn(async () => ({ ok: false, error, message: 'm' })) })
      expect(await scanText()).toEqual({ ok: false, error, message: 'm' })
    }
  )

  it('reports an app that predates scanText as unavailable', async () => {
    installBridge({ call: vi.fn(async () => ({ ok: false, error: 'unknownAction' })) })
    expect(await scanText()).toEqual({ ok: false, error: 'unavailable' })
  })

  it('is unavailable outside the app and never throws', async () => {
    expect(await scanText({ pattern: '\\d+' })).toEqual({ ok: false, error: 'unavailable' })
  })
})

describe('scanBarcode', () => {
  it('without options stays as it was: it resolves right away', async () => {
    const bridge = installBridge()
    expect(await scanBarcode()).toEqual({ ok: true })
    expect(bridge.call).toHaveBeenCalledWith('scanBarcode', {})
  })

  it('is unavailable outside the app', async () => {
    expect(await scanBarcode()).toEqual({ ok: false, error: 'unavailable' })
    expect(await scanBarcode({ formats: ['qr'] })).toEqual({ ok: false, error: 'unavailable' })
  })

  it('with formats resolves with the value', async () => {
    const bridge = installBridge({
      call: vi.fn(async () => ({ ok: true, value: '4006381333931' })),
    })
    const res = await scanBarcode({ formats: ['ean13', 'qr'] })
    expect(bridge.call).toHaveBeenCalledWith('scanBarcode', { formats: ['ean13', 'qr'] })
    expect(res).toEqual({ ok: true, value: '4006381333931' })
  })

  it('treats an answer without a value as the old app and waits for the callback', async () => {
    installBridge()
    const pending = scanBarcode({ formats: ['qr'] })
    await new Promise((resolve) => setTimeout(resolve))
    ;(window as unknown as { onBarcodeScanned: (v: string) => void }).onBarcodeScanned('XYZ')
    expect(await pending).toEqual({ ok: true, value: 'XYZ', oldApp: true })
  })

  it('passes failures through', async () => {
    installBridge({ call: vi.fn(async () => ({ ok: false, error: 'cancelled' })) })
    expect(await scanBarcode({ formats: ['qr'] })).toEqual({ ok: false, error: 'cancelled' })
  })

  it('warns about unknown formats', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    installBridge({ call: vi.fn(async () => ({ ok: true, value: 'v' })) })
    await scanBarcode({ formats: ['qr', 'nope' as never] })
    expect(warn.mock.calls[0]?.[0]).toContain('nope')
  })
})

describe('scanBarcodes', () => {
  it('sends multiple, formats and max and returns the values', async () => {
    const bridge = installBridge({ call: vi.fn(async () => ({ ok: true, values: ['a', 'b'] })) })
    const res = await scanBarcodes({ formats: ['ean13', 'qr'], max: 20 })
    expect(bridge.call).toHaveBeenCalledWith('scanBarcode', {
      multiple: true,
      formats: ['ean13', 'qr'],
      max: 20,
    })
    expect(res).toEqual({ ok: true, values: ['a', 'b'] })
  })

  it('sends only multiple without options', async () => {
    const bridge = installBridge({ call: vi.fn(async () => ({ ok: true, values: ['a'] })) })
    await scanBarcodes()
    expect(bridge.call).toHaveBeenCalledWith('scanBarcode', { multiple: true })
  })

  it('warns about max outside 1 to 200 and still sends it', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge({ call: vi.fn(async () => ({ ok: false, error: 'invalid' })) })
    expect(await scanBarcodes({ max: 201 })).toEqual({ ok: false, error: 'invalid' })
    expect(bridge.call).toHaveBeenCalledWith('scanBarcode', { multiple: true, max: 201 })
    expect(warn).toHaveBeenCalledOnce()
  })

  it('returns a one-entry list flagged oldApp for an app without the feature', async () => {
    installBridge()
    const seen: string[][] = []
    on('barcodesScanned', (values) => seen.push(values))
    const pending = scanBarcodes({ max: 5 })
    await new Promise((resolve) => setTimeout(resolve))
    ;(window as unknown as { onBarcodeScanned: (v: string) => void }).onBarcodeScanned('ONE')
    expect(await pending).toEqual({ ok: true, values: ['ONE'], oldApp: true })
  })

  it('is unavailable outside the app', async () => {
    expect(await scanBarcodes()).toEqual({ ok: false, error: 'unavailable' })
  })
})

describe('callbacks', () => {
  it('on() delivers the multi and text callbacks', () => {
    const texts: string[] = []
    const lists: string[][] = []
    on('textScanned', (t) => texts.push(t))
    on('barcodesScanned', (v) => lists.push(v))
    const w = window as unknown as {
      onTextScanned: (v: string) => void
      onBarcodesScanned: (v: string[]) => void
    }
    w.onTextScanned('AB-1')
    w.onBarcodesScanned(['1', '2'])
    expect(texts).toEqual(['AB-1'])
    expect(lists).toEqual([['1', '2']])
  })
})

describe('BARCODE_FORMATS', () => {
  it('lists the 13 names of the app', () => {
    expect(BARCODE_FORMATS).toHaveLength(13)
  })
})
