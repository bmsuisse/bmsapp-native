// Layout of the web view: keyboard, size class, orientation. Everything
// else (safe areas, `visualViewport`) is plain CSS and DOM.
// Details: docs/webapp-chrome-guide.md

import { hasFeature, type NativeFailure } from './bridge.js'
import { asFailure, badAnswer, callFeature, isRecord } from './internal.js'

/** The horizontal size class: iPhone portrait is `compact`, a wide iPad window `regular`. */
export type SizeClass = 'compact' | 'regular'
export type Orientation = 'portrait' | 'landscape'

/**
 * The layout of the web view. `width` and `height` are the web view's size in
 * CSS px, between the native bars. `keyboardHeight` is the height of the
 * keyboard that overlaps the web view in px (`0` without a keyboard).
 */
export type LayoutInfo = {
  keyboardHeight: number
  keyboardVisible: boolean
  sizeClass: SizeClass
  orientation: Orientation
  width: number
  height: number
}

export type GetLayoutResult = ({ ok: true } & LayoutInfo) | NativeFailure

function isLayout(value: unknown): value is LayoutInfo {
  if (!isRecord(value)) return false
  return (
    typeof value.keyboardHeight === 'number' &&
    typeof value.keyboardVisible === 'boolean' &&
    (value.sizeClass === 'compact' || value.sizeClass === 'regular') &&
    (value.orientation === 'portrait' || value.orientation === 'landscape') &&
    typeof value.width === 'number' &&
    typeof value.height === 'number'
  )
}

/**
 * The current layout of the web view (feature `layout`). `unavailable` in the
 * browser and in an app without the feature: use CSS media queries and
 * `visualViewport` there. Never throws.
 *
 * Prefer the `data-bms-size-class` and `data-bms-orientation` attributes and the
 * CSS property `--bms-keyboard-height` on `<html>`, which the app keeps up to date,
 * and `on('layoutChange', …)` for changes.
 */
export async function getLayout(): Promise<GetLayoutResult> {
  const answer = await callFeature('layout', 'getLayout')
  if (!answer.ok) return asFailure(answer)
  if (!isLayout(answer)) return badAnswer()
  const { keyboardHeight, keyboardVisible, sizeClass, orientation, width, height } = answer
  return { ok: true, keyboardHeight, keyboardVisible, sizeClass, orientation, width, height }
}

function visualViewportKeyboard(): number {
  if (typeof window === 'undefined' || !window.visualViewport) return 0
  const { height, offsetTop } = window.visualViewport
  return Math.max(0, Math.round(window.innerHeight - height - offsetTop))
}

/**
 * The height of the on-screen keyboard in px (`0` if there is none): `getLayout`
 * in the app, `visualViewport` in the browser and in an app without the feature
 * `layout`. Use it to keep an input bar above the keyboard. Never throws.
 */
export async function keyboardHeight(): Promise<number> {
  if (hasFeature('layout')) {
    const layout = await getLayout()
    if (layout.ok) return layout.keyboardHeight
  }
  return visualViewportKeyboard()
}
