// Speech to text: `dictate`. Microphone access of the page itself
// (`getUserMedia`) needs no function here, only the capability.
// Details: docs/voice-guide.md

import type { NativeFailure } from './bridge.js'
import { asFailure, badAnswer, callFeature, invalid, isRecord } from './internal.js'

/** Limits of `dictate`. */
export const DICTATE_LIMITS = {
  /** `maxSeconds` is 1 to this. */
  maxSeconds: 120,
  /** Default of `maxSeconds`. */
  defaultSeconds: 60,
  /** Entries of `contextualStrings`. */
  contextualStrings: 50,
} as const

export type DictateOptions = {
  /** BCP-47, e.g. `'de-CH'`. Default: the device language. */
  locale?: string
  /** 1 to 120; default 60. The sheet ends by itself after that. */
  maxSeconds?: number
  /** Names and terms the recognizer should expect (at most 50), e.g. article names. */
  contextualStrings?: readonly string[]
}

/** `locale` is the one that was used. */
export type DictateResult = { ok: true; text: string; locale: string } | NativeFailure

function dictateProblem(options: unknown): string | undefined {
  if (!isRecord(options)) return 'options have to be an object.'
  const { locale, maxSeconds, contextualStrings } = options
  if (locale !== undefined && (typeof locale !== 'string' || locale === '')) {
    return 'locale has to be a BCP-47 string such as "de-CH".'
  }
  if (
    maxSeconds !== undefined &&
    !(
      typeof maxSeconds === 'number' &&
      Number.isFinite(maxSeconds) &&
      maxSeconds >= 1 &&
      maxSeconds <= DICTATE_LIMITS.maxSeconds
    )
  ) {
    return `maxSeconds has to be a number from 1 to ${DICTATE_LIMITS.maxSeconds}.`
  }
  if (contextualStrings !== undefined) {
    if (
      !Array.isArray(contextualStrings) ||
      !contextualStrings.every((s) => typeof s === 'string')
    ) {
      return 'contextualStrings has to be a list of strings.'
    }
    if (contextualStrings.length > DICTATE_LIMITS.contextualStrings) {
      return `contextualStrings has ${contextualStrings.length} entries, at most ${DICTATE_LIMITS.contextualStrings} are allowed.`
    }
  }
  return undefined
}

/**
 * Dictation: opens a native sheet with a live transcript and Done/Cancel and
 * resolves with the text. Requires `microphone`. Offer a way to type as well.
 *
 * Errors: `cancelled` (the user cancelled), `denied` (microphone or speech
 * recognition is turned off for the app), `unavailable` (no recognizer for the
 * locale or on this device, an app without the feature `dictate`, or outside the
 * app), `capability` (no `microphone`), `invalid` (bad options; the app is not
 * asked). Never throws.
 */
export async function dictate(options: DictateOptions = {}): Promise<DictateResult> {
  const problem = dictateProblem(options)
  if (problem) return invalid('dictate', problem)
  const payload: Record<string, unknown> = {}
  if (options.locale !== undefined) payload.locale = options.locale
  if (options.maxSeconds !== undefined) payload.maxSeconds = options.maxSeconds
  if (options.contextualStrings !== undefined) {
    payload.contextualStrings = [...options.contextualStrings]
  }
  const answer = await callFeature('dictate', 'dictate', payload)
  if (!answer.ok) return asFailure(answer)
  const { text, locale } = answer as { text?: unknown; locale?: unknown }
  return typeof text === 'string' && typeof locale === 'string'
    ? { ok: true, text, locale }
    : badAnswer()
}
