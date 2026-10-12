// Scanning text and several barcodes with the camera: `scanText`, multi-code
// `scanBarcodes` and `scanBarcode` with options. `scanBarcode()` without options
// behaves as before (callback only).
// Details: docs/scan-guide.md

import { call, can, send, type NativeResult } from './bridge.js'
import { isDevelopment, warn } from './dev.js'
import { on } from './events.js'

/** The barcode kinds the scanner knows (Apple's names, lowercase first letter). */
export const BARCODE_FORMATS = [
  'aztec',
  'codabar',
  'code39',
  'code93',
  'code128',
  'dataMatrix',
  'ean8',
  'ean13',
  'i2of5',
  'itf14',
  'pdf417',
  'qr',
  'upce',
] as const

export type BarcodeFormat = (typeof BARCODE_FORMATS)[number]

/** Limits the app enforces. */
export const SCAN_LIMITS = {
  /** Characters of a `scanText` pattern. */
  patternLength: 200,
  /** Codes of one multi scan (also the upper bound of `max`). */
  codes: 200,
} as const

/**
 * Why a scan failed.
 *
 * - `invalid`: options of the wrong type or out of range; `message` is an English
 *   sentence for the developer — do not show it.
 * - `capability`: the web app has no `camera` capability (`message`: English, for developers).
 * - `unavailable`: no scanner on this device (simulator, old chip), it cannot be
 *   shown right now, or the page runs outside the app. `scanText` also reports an
 *   app that predates it (`unknownAction`) as `unavailable`. The `message` from
 *   the app is a sentence for the user.
 * - `denied`: camera access is turned off for the app; `message` is for the user.
 * - `cancelled`: the user closed the scanner without a result. No callback is called.
 * - `busy`: another scan is already open.
 */
export type ScanError =
  | 'invalid'
  | 'capability'
  | 'unavailable'
  | 'denied'
  | 'cancelled'
  | 'busy'
  | 'unknownAction'

export type ScanFailure = { ok: false; error: ScanError; message?: string }

// --- helpers ----------------------------------------------------------------

/**
 * Can this page scan at all? `true` if the app granted `camera`. There is no
 * way to know beforehand that the device has a scanner: handle `unavailable`.
 */
export function canScan(): boolean {
  return can('camera')
}

function failure(error: ScanError, message?: string): ScanFailure {
  return { ok: false, error, ...(message && { message }) }
}

function isFailure(result: unknown): result is { ok: false } {
  return typeof result === 'object' && result !== null && (result as { ok?: unknown }).ok === false
}

function asFailure(result: object): ScanFailure {
  const { error, message } = result as { error?: unknown; message?: unknown }
  return failure(
    typeof error === 'string' ? (error as ScanError) : 'unavailable',
    typeof message === 'string' ? message : undefined
  )
}

// --- scanText ---------------------------------------------------------------

export type ScanTextOptions = {
  /**
   * Only lines that match as a whole can be picked. A `string` is an ICU regular
   * expression (at most 200 characters), matched case-insensitively against the
   * WHOLE recognized line: `'\\d{4}'` accepts `1234` but not `12345` or `No. 1234`.
   * A `RegExp` is sent as its `source`; its `i` flag is dropped (matching is
   * always case-insensitive). The app uses ICU syntax, not JavaScript's: simple
   * patterns are the same, but `\d` matches digits of every script and
   * lookbehind, named groups and some escapes differ in details.
   * Empty or `null`: no filter.
   */
  pattern?: string | RegExp | null
}

export type ScanTextResult = { ok: true; text: string } | ScanFailure

function patternSource(pattern: string | RegExp | null | undefined): string | undefined {
  if (pattern == null) return undefined
  const dev = isDevelopment()
  let source: string
  if (typeof pattern === 'string') {
    source = pattern
  } else {
    source = pattern.source
    const flags = pattern.flags.replace('i', '')
    if (dev && flags) {
      warn('scanText', [
        `the RegExp flags "${flags}" are ignored: the app matches the whole line, case-insensitively.`,
      ])
    }
  }
  if (dev) {
    const warnings: string[] = []
    if (source.length > SCAN_LIMITS.patternLength) {
      warnings.push(
        `the pattern has ${source.length} characters, the app takes at most ${SCAN_LIMITS.patternLength}.`
      )
    }
    if (/\(\?<(?:[=!]|\w)/.test(source)) {
      warnings.push(
        'lookbehind and named groups differ in details between JavaScript and the ICU syntax of the app.'
      )
    }
    warn('scanText', warnings)
  }
  return source === '' ? undefined : source
}

/**
 * Reads text with the camera: the recognized lines are highlighted and the user
 * taps one. Requires `camera`, real iPhones only. `on('textScanned', …)` also
 * fires with the text — do not handle the result twice.
 *
 * An app that predates `scanText` answers `unknownAction`, reported here as
 * `unavailable`; outside the app the result is `unavailable` as well. Keep a way
 * to type the value in.
 */
export async function scanText(options: ScanTextOptions = {}): Promise<ScanTextResult> {
  const pattern = patternSource(options.pattern)
  const result = await call('scanText', pattern === undefined ? {} : { pattern })
  if (isFailure(result)) {
    const failed = asFailure(result)
    return failed.error === 'unknownAction' ? { ...failed, error: 'unavailable' } : failed
  }
  const text = (result as { text?: unknown }).text
  return typeof text === 'string' ? { ok: true, text } : failure('unavailable')
}

// --- barcodes ---------------------------------------------------------------

export type ScanBarcodeOptions = {
  /** Limits the barcode kinds; unknown names are ignored. Without a usable one every kind is accepted. */
  formats?: readonly BarcodeFormat[]
}

export type ScanBarcodesOptions = ScanBarcodeOptions & {
  /** 1 to 200: the scanner closes by itself with that many codes. Without it: 200. */
  max?: number
}

/**
 * `oldApp: true`: the app predates this feature, ignored the options and ran the
 * old single scan. The code was taken from `on('barcodeScanned')`, so `formats`
 * and `max` were NOT applied.
 */
export type ScanBarcodeResult = { ok: true; value: string; oldApp?: true } | ScanFailure
export type ScanBarcodesResult = { ok: true; values: string[]; oldApp?: true } | ScanFailure

function barcodeWarnings(options: ScanBarcodesOptions): void {
  if (!isDevelopment()) return
  const warnings: string[] = []
  const unknown = (options.formats ?? []).filter(
    (name) => !(BARCODE_FORMATS as readonly string[]).includes(name)
  )
  if (unknown.length)
    warnings.push(`unknown formats are ignored by the app: ${unknown.join(', ')}.`)
  const { max } = options
  if (max !== undefined && !(Number.isInteger(max) && max >= 1 && max <= SCAN_LIMITS.codes)) {
    warnings.push(`max has to be a whole number from 1 to ${SCAN_LIMITS.codes}, got ${max}.`)
  }
  warn('scanBarcode', warnings)
}

/**
 * Listens for `on('barcodeScanned')` from now on. Subscribed BEFORE the call: an
 * app without this feature may call the page before it answers.
 */
function listenForBarcode(): { code: Promise<string>; stop: () => void } {
  let stop = () => {}
  const code = new Promise<string>((resolve) => {
    stop = on('barcodeScanned', (value) => {
      stop()
      resolve(value)
    })
  })
  return { code, stop }
}

async function scanCodes(
  payload: Record<string, unknown>,
  multiple: boolean
): Promise<ScanBarcodeResult | ScanBarcodesResult> {
  const legacy = listenForBarcode()
  const result = await send('scanBarcode', payload)
  if (isFailure(result)) {
    legacy.stop()
    return asFailure(result)
  }
  const { value, values } = result as { value?: unknown; values?: unknown }
  if (multiple && Array.isArray(values) && values.every((v) => typeof v === 'string')) {
    legacy.stop()
    return { ok: true, values }
  }
  if (!multiple && typeof value === 'string') {
    legacy.stop()
    return { ok: true, value }
  }
  // `{ ok: true }` without a code: an app without this feature.
  const code = await legacy.code
  return multiple
    ? { ok: true, values: [code], oldApp: true }
    : { ok: true, value: code, oldApp: true }
}

/**
 * Opens the native barcode/QR scanner. Requires `camera`.
 *
 * Without options the promise resolves right away and the code arrives only
 * through `on('barcodeScanned', value => …)`.
 *
 * With options (`formats`) the promise resolves with the code once the scanner
 * closes. The callback fires as well — do not handle the result twice. An app
 * that predates this feature ignores the options; the promise then waits for the
 * callback and resolves with `oldApp: true`. That app reports no cancel, so the
 * promise stays pending if the user closes the scanner.
 */
export function scanBarcode(): Promise<NativeResult>
export function scanBarcode(options: ScanBarcodeOptions): Promise<ScanBarcodeResult>
export function scanBarcode(
  options?: ScanBarcodeOptions
): Promise<NativeResult | ScanBarcodeResult> {
  if (!options) return send('scanBarcode')
  barcodeWarnings(options)
  const payload = options.formats?.length ? { formats: [...options.formats] } : {}
  return scanCodes(payload, false) as Promise<ScanBarcodeResult>
}

/**
 * Collects several barcodes: the scanner stays open and lists every distinct code;
 * "Done" resolves with all of them in scan order, "Cancel" with `cancelled`.
 * `on('barcodesScanned')` fires as well. An app that predates this feature scans
 * one code only: `values` then has one entry and `oldApp: true` (see `scanBarcode`).
 */
export function scanBarcodes(options: ScanBarcodesOptions = {}): Promise<ScanBarcodesResult> {
  barcodeWarnings(options)
  const payload: Record<string, unknown> = { multiple: true }
  if (options.formats?.length) payload.formats = [...options.formats]
  if (options.max !== undefined) payload.max = options.max
  return scanCodes(payload, true) as Promise<ScanBarcodesResult>
}
