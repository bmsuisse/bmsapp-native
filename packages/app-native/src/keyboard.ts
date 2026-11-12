// The on-screen keyboard toolbar and hardware key commands.
// Details: docs/webapp-chrome-guide.md

import type { NativeFailure } from './bridge.js'
import {
  asFailure,
  callFeature,
  invalid,
  isRecord,
  nonEmptyString,
  textLength,
} from './internal.js'

/** Limits of the toolbar and the key commands. */
export const KEYBOARD_LIMITS = { toolbarItems: 6, keyCommands: 60 } as const

export type KeyboardToolbarItem = {
  /** Comes back with the tap. */
  id: string
  /** Shown as delivered. At least `label` or `icon`. */
  label?: string
  /** SF Symbol. */
  icon?: string
  /** Default `plain`. */
  style?: 'plain' | 'prominent'
}

export type KeyboardToolbarOptions = {
  /** At most 6. `[]` removes the toolbar. */
  items: KeyboardToolbarItem[]
  /** Adds a trailing Done button that blurs the field. */
  done?: boolean
}

function toolbarProblem(options: unknown): string | undefined {
  if (!isRecord(options) || !Array.isArray(options.items)) return 'options need a list of items.'
  if (options.items.length > KEYBOARD_LIMITS.toolbarItems) {
    return `${options.items.length} items, the app takes at most ${KEYBOARD_LIMITS.toolbarItems}.`
  }
  if (options.done !== undefined && typeof options.done !== 'boolean')
    return 'done has to be a boolean.'
  for (const [i, item] of options.items.entries()) {
    const at = `items[${i}]`
    if (!isRecord(item) || !nonEmptyString(item.id)) return `${at} needs an id.`
    const hasLabel = typeof item.label === 'string' && item.label !== ''
    const hasIcon = typeof item.icon === 'string' && item.icon !== ''
    if (!hasLabel && !hasIcon) return `${at} needs a label or an icon.`
    if (item.style !== undefined && item.style !== 'plain' && item.style !== 'prominent') {
      return `${at}.style has to be plain or prominent.`
    }
  }
  return undefined
}

/**
 * A native toolbar above the on-screen keyboard, shown while a field of the page has
 * focus: "Previous / Next / Add line / Done". A tap arrives as
 * `on('keyboardToolbarTap', ({ id }) => …)` and **keeps the focus**. With `done: true`
 * a trailing Done button blurs the field. Not shown with a hardware keyboard.
 * `{ items: [] }` removes it. Requires `customChrome` and the feature `keyboardToolbar`.
 *
 * Errors: `invalid` (more than 6 items, an item without label and icon, … answered
 * without asking the app), `capability`, `unavailable` (browser, app without the
 * feature: show your own toolbar).
 */
export async function setKeyboardToolbar(
  options: KeyboardToolbarOptions
): Promise<{ ok: true } | NativeFailure> {
  const problem = toolbarProblem(options)
  if (problem) return invalid('setKeyboardToolbar', problem)
  const answer = await callFeature('keyboardToolbar', 'setKeyboardToolbar', { ...options })
  return answer.ok ? { ok: true } : asFailure(answer)
}

// --- Key commands --------------------------------------------------------------

export type KeyCommandKey =
  | 'up'
  | 'down'
  | 'left'
  | 'right'
  | 'escape'
  | 'return'
  | 'tab'
  | 'delete'
export type KeyCommandModifier = 'command' | 'option' | 'shift' | 'control'

const NAMED_KEYS: readonly string[] = [
  'up',
  'down',
  'left',
  'right',
  'escape',
  'return',
  'tab',
  'delete',
]
const MODIFIERS: readonly string[] = ['command', 'option', 'shift', 'control']

export type KeyCommand = {
  /** Comes back with `on('keyCommand')`. */
  id: string
  /** One character (`'k'`), or `up`, `down`, `left`, `right`, `escape`, `return`, `tab`, `delete`. */
  input: KeyCommandKey | (string & {})
  /** Possibly empty. */
  modifiers: KeyCommandModifier[]
  /** Shown as delivered in the ⌘-hold overlay and the menu bar. */
  title: string
  /** The menu bar menu it appears under. */
  group?: string
}

function keyCommandsProblem(options: unknown): string | undefined {
  if (!isRecord(options) || !Array.isArray(options.commands))
    return 'options need a list of commands.'
  if (options.commands.length > KEYBOARD_LIMITS.keyCommands) {
    return `${options.commands.length} commands, the app takes at most ${KEYBOARD_LIMITS.keyCommands}.`
  }
  for (const [i, command] of options.commands.entries()) {
    const at = `commands[${i}]`
    if (!isRecord(command) || !nonEmptyString(command.id)) return `${at} needs an id.`
    const { input, modifiers } = command
    if (!nonEmptyString(input) || !(NAMED_KEYS.includes(input) || textLength(input) === 1)) {
      return `${at}.input has to be one character or one of ${NAMED_KEYS.join(', ')}.`
    }
    if (
      !Array.isArray(modifiers) ||
      !modifiers.every((m) => typeof m === 'string' && MODIFIERS.includes(m))
    ) {
      return `${at}.modifiers has to be a list of ${MODIFIERS.join(', ')} (possibly empty).`
    }
    if (!nonEmptyString(command.title)) return `${at} needs a title.`
    if (command.group !== undefined && typeof command.group !== 'string')
      return `${at}.group has to be a string.`
  }
  return undefined
}

/**
 * Registers hardware key commands (Cmd+K, Cmd+F, …). They show up in the iPad ⌘-hold
 * overlay and the menu bar under their `group`. **The app consumes a registered
 * command** and calls `on('keyCommand', ({ id }) => …)` instead of letting the DOM
 * `keydown` through; keys that are not registered keep reaching the page as before.
 * A command without modifiers fires only while no text field of the page has focus.
 * Only with a hardware keyboard. `{ commands: [] }` removes them. At most 60. Requires
 * `customChrome` and the feature `keyCommands`.
 *
 * ```ts
 * await setKeyCommands({ commands: [
 *   { id: 'search', input: 'k', modifiers: ['command'], title: 'Search', group: 'Offers' },
 *   { id: 'next', input: 'down', modifiers: [], title: 'Next line', group: 'Navigate' },
 * ] })
 * on('keyCommand', ({ id }) => run(id))
 * ```
 *
 * Keep a `keydown` listener for browsers: it does not hear a registered command in the
 * app, so nothing fires twice.
 */
export async function setKeyCommands(options: {
  commands: KeyCommand[]
}): Promise<{ ok: true } | NativeFailure> {
  const problem = keyCommandsProblem(options)
  if (problem) return invalid('setKeyCommands', problem)
  const answer = await callFeature('keyCommands', 'setKeyCommands', {
    commands: [...options.commands],
  })
  return answer.ok ? { ok: true } : asFailure(answer)
}
