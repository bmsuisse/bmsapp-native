// Shared by the 2026-11 functions (documents, voice, layout, preview, tokens).
// Not exported from the package.

import { call, hasFeature, type Feature, type NativeFailure, type NativeResult } from './bridge.js'
import { isDevelopment, warn } from './dev.js'

type Message = Record<string, unknown>

/** A failure that is the same as "this app cannot do it". */
export function unavailable(message?: string): NativeFailure {
  return { ok: false, error: 'unavailable', ...(message && { message }) }
}

/**
 * The payload is invalid: answer `invalid` WITHOUT calling the app. In
 * development builds the reason is also logged (like `scan.ts` does).
 */
export function invalid(kind: string, message: string): NativeFailure {
  if (isDevelopment()) warn(kind, [message])
  return { ok: false, error: 'invalid', message }
}

/**
 * `call`, but only if the app lists the feature: an app without it answers
 * `unavailable` without being asked, and so does an app that still answers
 * `unknownAction`. Never throws.
 */
export async function callFeature<T extends object = object>(
  feature: Feature,
  action: string,
  payload: Message = {}
): Promise<NativeResult<T> | NativeFailure> {
  if (!hasFeature(feature)) return unavailable()
  const result = await call<T>(action, payload)
  if (!result.ok && result.error === 'unknownAction') return unavailable()
  return result
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Keeps `error` and `message` of an app failure, whatever else it carries. */
export function asFailure(result: { ok: false }): NativeFailure {
  const { error, message } = result as { error?: unknown; message?: unknown }
  return {
    ok: false,
    error: typeof error === 'string' ? error : 'failed',
    ...(typeof message === 'string' && { message }),
  }
}

export function badAnswer(): NativeFailure {
  return { ok: false, error: 'failed', message: 'The app answered with an unexpected result.' }
}

export function utf8Length(text: string): number {
  return new TextEncoder().encode(text).length
}

// --- Payload checks shared by scanDocument and pickFiles ---------------------

export const CONTEXT_MAX_BYTES = 4096
export const KIND_PATTERN = /^[a-z0-9_-]{1,32}$/

/** `context`: a JSON object of at most 4096 bytes serialized. `null`/`undefined`: not given. */
export function contextProblem(context: unknown): string | undefined {
  if (context === undefined || context === null) return undefined
  if (!isRecord(context)) return 'context has to be a plain JSON object.'
  let json: string | undefined
  try {
    json = JSON.stringify(context)
  } catch {
    return 'context cannot be serialized to JSON.'
  }
  if (json === undefined) return 'context cannot be serialized to JSON.'
  const bytes = utf8Length(json)
  if (bytes > CONTEXT_MAX_BYTES) {
    return `context is ${bytes} bytes serialized, the app takes at most ${CONTEXT_MAX_BYTES}.`
  }
  return undefined
}

export function kindProblem(kind: unknown): string | undefined {
  if (kind === undefined) return undefined
  if (typeof kind !== 'string' || !KIND_PATTERN.test(kind)) {
    return 'kind has to be 1 to 32 characters of a-z, 0-9, "_" and "-".'
  }
  return undefined
}

export function modeProblem(mode: unknown): string | undefined {
  if (mode === undefined || mode === 'upload' || mode === 'return') return undefined
  return 'mode has to be "upload" or "return".'
}

export function booleanProblem(name: string, value: unknown): string | undefined {
  return value === undefined || typeof value === 'boolean'
    ? undefined
    : `${name} has to be a boolean.`
}

// --- Shared by the 2026-11b functions ------------------------------------------

/** A rectangle in CSS px relative to the web view's visible viewport. */
export type Anchor = { x: number; y: number; width: number; height: number }

export function anchorProblem(anchor: unknown): string | undefined {
  if (!isRecord(anchor)) return 'anchor has to be { x, y, width, height } in CSS px.'
  for (const key of ['x', 'y', 'width', 'height'] as const) {
    if (typeof anchor[key] !== 'number' || !Number.isFinite(anchor[key])) {
      return `anchor.${key} has to be a finite number.`
    }
  }
  return undefined
}

/** Characters (code points), not UTF-16 units. */
export function textLength(text: string): number {
  return Array.from(text).length
}

export function nonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value !== ''
}

/**
 * `url` on the page's own origin (absolute or relative). Returns the absolute
 * URL, or the reason it is not one.
 */
export function sameOriginUrl(
  url: unknown,
  name = 'url'
): { problem: string; absolute?: undefined } | { problem?: undefined; absolute: string } {
  if (!nonEmptyString(url)) {
    return { problem: `${name} has to be a URL on the web app’s own origin.` }
  }
  if (typeof location === 'undefined') {
    return { problem: 'there is no page to resolve url against.' }
  }
  let absolute: URL
  try {
    absolute = new URL(url, location.href)
  } catch {
    return { problem: `${name} is not a valid URL.` }
  }
  if (absolute.origin !== location.origin) {
    return { problem: `${name} has to be on the web app’s own origin.` }
  }
  return { absolute: absolute.href }
}
