// Menus, alerts, action sheets and pickers that iOS draws natively: `showMenu`
// (anchored, with lazy submenus), `showAlert`, `showPicker`. The toast with an
// action is `toast` in ui.ts. The page keeps its own UI where the app has none:
// none of these falls back to `window.confirm` or `prompt`.
// Details: docs/menus-and-alerts-guide.md

import type { NativeFailure } from './bridge.js'
import { on } from './events.js'
import { isDevelopment, warn } from './dev.js'
import {
  anchorProblem,
  asFailure,
  badAnswer,
  callFeature,
  invalid,
  isRecord,
  nonEmptyString,
  textLength,
  type Anchor,
} from './internal.js'
import { call } from './bridge.js'

export type { Anchor }

/** Limits of menus. The app answers `invalid` beyond them. */
export const MENU_LIMITS = {
  /** Levels of submenus below the root menu. */
  depth: 2,
  /** Items of one menu, all levels together. */
  items: 80,
  /** Characters of a label. */
  label: 80,
  /** Seconds the page has for the answer to a lazy submenu (`menuItems`). */
  lazySeconds: 5,
} as const

/**
 * One row of a native menu (`showMenu`, `actionButtons[].menu`, `title.menu`).
 * Not the same as the `MenuItem` of the hamburger menu (`setChrome({ menu })`).
 */
export type NativeMenuItem = {
  /** Unique within the menu, all levels together. Comes back as the result. */
  id: string
  /** At most 80 characters. Shown as delivered: localize it yourself. */
  label: string
  subtitle?: string
  /** SF Symbol name. */
  icon?: string
  destructive?: boolean
  disabled?: boolean
  /** Shows a check mark. */
  checked?: boolean
  /**
   * A submenu: sections, or `"lazy"` to load them when the user opens the item (the
   * page answers `onMenuExpand`; `showMenu` does it with `loadChildren`).
   */
  children?: NativeMenuSection[] | 'lazy'
  /** Lazy items only: the disabled row shown if the page does not answer in 5 s. Default `–`. */
  lazyFailedLabel?: string
}

export type NativeMenuSection = { title?: string; items: NativeMenuItem[] }

/** What the app asks for when the user opens a lazy item. */
export type MenuExpandEvent = { menuId: string; itemId: string; requestId: string }

type Walk = {
  problems: string[]
  ids: Set<string>
  items: number
  /** Depth (levels below the root) of the lazy items found, by item id. */
  lazy: Map<string, number>
}

function newWalk(): Walk {
  return { problems: [], ids: new Set(), items: 0, lazy: new Map() }
}

function walkSections(sections: unknown, depth: number, where: string, walk: Walk): void {
  if (!Array.isArray(sections)) {
    walk.problems.push(`${where} has to be a list of sections.`)
    return
  }
  sections.forEach((section: unknown, s) => {
    const at = `${where}[${s}]`
    if (!isRecord(section) || !Array.isArray(section.items)) {
      walk.problems.push(`${at} needs a list of items.`)
      return
    }
    if (section.title !== undefined && typeof section.title !== 'string') {
      walk.problems.push(`${at}.title has to be a string.`)
    }
    section.items.forEach((item: unknown, i) => walkItem(item, depth, `${at}.items[${i}]`, walk))
  })
}

function walkItem(item: unknown, depth: number, at: string, walk: Walk): void {
  walk.items += 1
  if (!isRecord(item)) {
    walk.problems.push(`${at} has to be an object.`)
    return
  }
  const { id, label, children } = item
  if (!nonEmptyString(id)) walk.problems.push(`${at}.id has to be a non-empty string.`)
  else if (walk.ids.has(id)) walk.problems.push(`${at}: the id "${id}" is used twice in the menu.`)
  else walk.ids.add(id)
  if (typeof label !== 'string') walk.problems.push(`${at}.label has to be a string.`)
  else if (textLength(label) > MENU_LIMITS.label) {
    walk.problems.push(
      `${at}: the label has ${textLength(label)} characters, at most ${MENU_LIMITS.label}.`
    )
  }
  for (const key of ['destructive', 'disabled', 'checked'] as const) {
    if (item[key] !== undefined && typeof item[key] !== 'boolean') {
      walk.problems.push(`${at}.${key} has to be a boolean.`)
    }
  }
  if (children === undefined) return
  if (children === 'lazy') {
    if (nonEmptyString(id)) walk.lazy.set(id, depth)
    return
  }
  if (depth + 1 > MENU_LIMITS.depth) {
    walk.problems.push(
      `${at}: submenus are nested too deep, at most ${MENU_LIMITS.depth} levels below the root.`
    )
    return
  }
  walkSections(children, depth + 1, `${at}.children`, walk)
}

/**
 * Checks menu sections against the limits of the app and returns one sentence per
 * problem; empty means fine: at most 2 levels of submenus below the root, at most 80
 * items in total, labels of at most 80 characters, ids unique within the menu.
 * `showMenu` and `setChrome` use it; the app enforces the limits either way.
 */
export function menuLimitWarnings(sections: readonly NativeMenuSection[]): string[] {
  const walk = newWalk()
  walkSections(sections, 0, 'sections', walk)
  if (walk.items > MENU_LIMITS.items) {
    walk.problems.push(`${walk.items} items, the app takes at most ${MENU_LIMITS.items}.`)
  }
  return walk.problems
}

// --- showMenu ----------------------------------------------------------------

export type ShowMenuOptions = {
  /** Echoed in `onNativeMenuExpand`; generated if missing and `loadChildren` is given. */
  id?: string
  /** Where the menu comes from, in CSS px relative to the visible viewport (see `anchorOf`). */
  anchor: Anchor
  /** iPhone: the card that is lifted from the anchor. */
  preview?: { title: string; subtitle?: string }
  sections: NativeMenuSection[]
  /**
   * Answers the lazy items (`children: 'lazy'`): called when the user opens one. The app
   * shows a loading row and waits 5 seconds; after that it shows a disabled row with
   * the item's `lazyFailedLabel` (or `–`). A rejection or an invalid answer is not
   * answered, so the user sees that row after 5 seconds.
   */
  loadChildren?: (itemId: string) => NativeMenuSection[] | Promise<NativeMenuSection[]>
}

/** `id` is the id of the chosen item. */
export type ShowMenuResult = { ok: true; id: string } | NativeFailure

type MenuEntry = {
  loadChildren: NonNullable<ShowMenuOptions['loadChildren']>
  walk: Walk
}

const openMenus = new Map<string, MenuEntry>()
let listeningForExpand = false

function listenForExpand(): void {
  if (listeningForExpand) return
  listeningForExpand = true
  on('menuExpand', (event) => void expand(event))
}

async function expand(event: MenuExpandEvent): Promise<void> {
  const entry = isRecord(event) ? openMenus.get(event.menuId) : undefined
  if (!entry) return
  const { itemId, requestId } = event
  let sections: NativeMenuSection[]
  try {
    sections = await entry.loadChildren(itemId)
  } catch (error) {
    if (isDevelopment()) warn('showMenu', [`loadChildren("${itemId}") failed: ${String(error)}`])
    return
  }
  if (openMenus.get(event.menuId) !== entry) return // the menu is closed
  const depth = (entry.walk.lazy.get(itemId) ?? -1) + 1
  const walk: Walk = {
    problems: [],
    ids: entry.walk.ids,
    items: entry.walk.items,
    lazy: entry.walk.lazy,
  }
  if (depth > MENU_LIMITS.depth)
    walk.problems.push('the lazy item is already at the deepest level.')
  else walkSections(sections, depth, 'sections', walk)
  if (walk.items > MENU_LIMITS.items) {
    walk.problems.push(`${walk.items} items, the app takes at most ${MENU_LIMITS.items}.`)
  }
  if (walk.problems.length) {
    if (isDevelopment())
      warn(
        'showMenu',
        walk.problems.map((p) => `loadChildren("${itemId}"): ${p}`)
      )
    return
  }
  entry.walk.items = walk.items
  await call('menuItems', { requestId, sections })
}

function menuProblem(options: unknown): string | undefined {
  if (!isRecord(options)) return 'options have to be { anchor, sections }.'
  const anchor = anchorProblem(options.anchor)
  if (anchor) return anchor
  if (options.id !== undefined && !nonEmptyString(options.id))
    return 'id has to be a non-empty string.'
  if (options.preview !== undefined) {
    const { preview } = options
    if (!isRecord(preview) || !nonEmptyString(preview.title)) return 'preview needs a title.'
    if (preview.subtitle !== undefined && typeof preview.subtitle !== 'string') {
      return 'preview.subtitle has to be a string.'
    }
  }
  return menuLimitWarnings(options.sections as NativeMenuSection[])[0]
}

/**
 * Opens a native menu at `anchor` and resolves with the id of the chosen item.
 * iPhone: a context menu with a lifted card built from `preview`. iPad: a menu at
 * the anchor (a secondary trackpad click opens the same one). Requires
 * `customChrome` and the feature `menus`.
 *
 * ```ts
 * const res = await showMenu({
 *   anchor: anchorOf(button),
 *   preview: { title: 'Offer 4711', subtitle: 'Müller AG' },
 *   sections: [{ items: [
 *     { id: 'open', label: 'Open', icon: 'doc' },
 *     { id: 'export', label: 'Export as …', children: 'lazy' },
 *     { id: 'delete', label: 'Delete', icon: 'trash', destructive: true },
 *   ] }],
 *   loadChildren: async () => await api.exportFormats(),
 * })
 * if (res.ok) run(res.id)
 * ```
 *
 * Limits (`MENU_LIMITS`): 2 levels of submenus, 80 items, labels of 80 characters,
 * unique ids. A menu beyond them answers `invalid` without asking the app. Errors:
 * `cancelled` (dismissed), `invalid`, `busy` (a menu is already open), `capability`,
 * `unavailable` (browser, app without the feature): keep your own menu for that.
 */
export async function showMenu(options: ShowMenuOptions): Promise<ShowMenuResult> {
  const problem = menuProblem(options)
  if (problem) return invalid('showMenu', problem)
  const { loadChildren, ...definition } = options
  const walk = newWalk()
  walkSections(options.sections, 0, 'sections', walk)
  if (isDevelopment() && !loadChildren && walk.lazy.size) {
    warn('showMenu', [
      'there are lazy items but no loadChildren: the user will see the failed row.',
    ])
  }
  if (isDevelopment() && loadChildren && !walk.lazy.size) {
    warn('showMenu', ['loadChildren is given but no item has children: "lazy".'])
  }
  const id = definition.id ?? (loadChildren ? newId() : undefined)
  const payload = { ...definition, ...(id !== undefined && { id }) }
  if (!loadChildren || id === undefined)
    return toMenuResult(await callFeature('menus', 'showMenu', payload))
  if (openMenus.has(id)) {
    return { ok: false, error: 'busy', message: `A menu with the id "${id}" is already open.` }
  }
  const entry: MenuEntry = { loadChildren, walk }
  openMenus.set(id, entry)
  listenForExpand()
  try {
    return toMenuResult(await callFeature('menus', 'showMenu', payload))
  } finally {
    if (openMenus.get(id) === entry) openMenus.delete(id)
  }
}

function toMenuResult(answer: { ok: boolean }): ShowMenuResult {
  if (!answer.ok) return asFailure(answer as { ok: false })
  const { id } = answer as { id?: unknown }
  return typeof id === 'string' ? { ok: true, id } : badAnswer()
}

function newId(): string {
  const c = globalThis.crypto
  if (typeof c?.randomUUID === 'function') return c.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/**
 * The rectangle of an element in the form the app wants it: CSS px relative to the
 * visible viewport (what `getBoundingClientRect()` returns), as `{ x, y, width, height }`.
 */
export function anchorOf(element: Element): Anchor {
  const { x, y, width, height } = element.getBoundingClientRect()
  return { x, y, width, height }
}

// --- showAlert ----------------------------------------------------------------

/** Limits of alerts. */
export const ALERT_LIMITS = { actions: 6 } as const

export type AlertAction = {
  /** Comes back as the result. */
  id: string
  /** Shown as delivered. */
  label: string
  style?: 'default' | 'cancel' | 'destructive'
  /** The bold, default button. */
  preferred?: boolean
}

export type AlertTextField = {
  placeholder?: string
  value?: string
  keyboard?: 'default' | 'decimal' | 'number' | 'email'
  maxLength?: number
}

export type ShowAlertOptions = {
  title: string
  message?: string
  /** Default `alert`. */
  style?: 'alert' | 'actionSheet'
  /**
   * iPad: an action sheet is a popover at `anchor` (without it the app centres it).
   * Ignored by alerts.
   */
  anchor?: Anchor
  /** 1 to 6 buttons, at most one `cancel`. */
  actions: AlertAction[]
  /** An input line. `alert` only. */
  textField?: AlertTextField
}

/** `text` only with `textField`. */
export type ShowAlertResult = { ok: true; id: string; text?: string } | NativeFailure

function alertProblem(options: unknown): string | undefined {
  if (!isRecord(options)) return 'options have to be { title, actions }.'
  if (!nonEmptyString(options.title)) return 'title has to be a non-empty string.'
  if (options.message !== undefined && typeof options.message !== 'string') {
    return 'message has to be a string.'
  }
  const style = options.style ?? 'alert'
  if (style !== 'alert' && style !== 'actionSheet')
    return 'style has to be "alert" or "actionSheet".'
  if (options.anchor !== undefined) {
    const anchor = anchorProblem(options.anchor)
    if (anchor) return anchor
  }
  const { actions } = options
  if (!Array.isArray(actions) || actions.length < 1 || actions.length > ALERT_LIMITS.actions) {
    return `actions needs 1 to ${ALERT_LIMITS.actions} entries.`
  }
  let cancels = 0
  for (const [i, action] of actions.entries()) {
    if (!isRecord(action) || !nonEmptyString(action.id) || typeof action.label !== 'string') {
      return `actions[${i}] needs an id and a label.`
    }
    if (
      action.style !== undefined &&
      action.style !== 'default' &&
      action.style !== 'cancel' &&
      action.style !== 'destructive'
    ) {
      return `actions[${i}].style has to be default, cancel or destructive.`
    }
    if (action.preferred !== undefined && typeof action.preferred !== 'boolean') {
      return `actions[${i}].preferred has to be a boolean.`
    }
    if (action.style === 'cancel') cancels += 1
  }
  if (cancels > 1) return 'at most one action can be a cancel action.'
  return textFieldProblem(options.textField, style)
}

function textFieldProblem(field: unknown, style: unknown): string | undefined {
  if (field === undefined) return undefined
  if (style !== 'alert') return 'textField only works with style "alert".'
  if (!isRecord(field)) return 'textField has to be an object.'
  for (const key of ['placeholder', 'value'] as const) {
    if (field[key] !== undefined && typeof field[key] !== 'string') {
      return `textField.${key} has to be a string.`
    }
  }
  const { keyboard, maxLength } = field
  if (
    keyboard !== undefined &&
    keyboard !== 'default' &&
    keyboard !== 'decimal' &&
    keyboard !== 'number' &&
    keyboard !== 'email'
  ) {
    return 'textField.keyboard has to be default, decimal, number or email.'
  }
  if (maxLength !== undefined && !(Number.isInteger(maxLength) && (maxLength as number) >= 1)) {
    return 'textField.maxLength has to be a whole number of at least 1.'
  }
  return undefined
}

/**
 * A native alert or action sheet; resolves with the `id` of the tapped action (and
 * the typed `text` with a `textField`). Requires `customChrome` and the feature
 * `alerts`.
 *
 * ```ts
 * const res = await showAlert({
 *   title: 'Delete offer?',
 *   message: 'This cannot be undone.',
 *   actions: [
 *     { id: 'cancel', label: 'Cancel', style: 'cancel' },
 *     { id: 'delete', label: 'Delete', style: 'destructive' },
 *   ],
 * })
 * if (res.ok && res.id === 'delete') await remove()
 * ```
 *
 * A tap outside an action sheet counts as the `cancel` action, or `cancelled` if there
 * is none. Errors: `cancelled`, `invalid` (the package answers it without asking the
 * app), `capability`, `unavailable`. **There is no `window.confirm` fallback**: where
 * it is `unavailable` the page shows its own dialog.
 */
export async function showAlert(options: ShowAlertOptions): Promise<ShowAlertResult> {
  const problem = alertProblem(options)
  if (problem) return invalid('showAlert', problem)
  const answer = await callFeature('alerts', 'showAlert', { ...options })
  if (!answer.ok) return asFailure(answer)
  const { id, text } = answer as { id?: unknown; text?: unknown }
  if (typeof id !== 'string') return badAnswer()
  return typeof text === 'string' ? { ok: true, id, text } : { ok: true, id }
}

// --- showPicker ---------------------------------------------------------------

export const PICKER_LIMITS = { options: 200 } as const

export type PickerOption = { value: string; label: string; subtitle?: string }

export type ShowPickerOptions = {
  kind: 'date' | 'option'
  /** iPad: a popover at the anchor; iPhone ignores it. */
  anchor?: Anchor
  title?: string
  /** `date`: `YYYY-MM-DD`. `option`: the `value` of the selected option. */
  value?: string
  /** `date` only, `YYYY-MM-DD`. */
  min?: string
  max?: string
  /** `option` only: 1 to 200. */
  options?: PickerOption[]
}

export type ShowPickerResult = { ok: true; value: string } | NativeFailure

function isDate(value: unknown): boolean {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [y, m, d] = value.split('-').map(Number) as [number, number, number]
  const date = new Date(Date.UTC(y, m - 1, d))
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d
}

function pickerProblem(options: unknown): string | undefined {
  if (!isRecord(options)) return 'options have to be { kind }.'
  const { kind } = options
  if (kind !== 'date' && kind !== 'option') return 'kind has to be "date" or "option".'
  if (options.anchor !== undefined) {
    const anchor = anchorProblem(options.anchor)
    if (anchor) return anchor
  }
  if (options.title !== undefined && typeof options.title !== 'string')
    return 'title has to be a string.'
  if (options.value !== undefined && typeof options.value !== 'string')
    return 'value has to be a string.'
  if (kind === 'date') {
    for (const key of ['value', 'min', 'max'] as const) {
      if (options[key] !== undefined && !isDate(options[key])) {
        return `${key} has to be a date as YYYY-MM-DD.`
      }
    }
    return undefined
  }
  const { options: list } = options
  if (!Array.isArray(list) || list.length < 1 || list.length > PICKER_LIMITS.options) {
    return `options needs 1 to ${PICKER_LIMITS.options} entries.`
  }
  for (const [i, option] of list.entries()) {
    if (!isRecord(option) || typeof option.value !== 'string' || typeof option.label !== 'string') {
      return `options[${i}] needs a value and a label.`
    }
    if (option.subtitle !== undefined && typeof option.subtitle !== 'string') {
      return `options[${i}].subtitle has to be a string.`
    }
  }
  return undefined
}

/**
 * A native date or option picker; resolves with the chosen `value`. iPhone: a compact
 * bottom sheet. iPad: a popover at `anchor`. Requires `customChrome` and the feature
 * `pickers`.
 *
 * Errors: `cancelled`, `invalid` (answered by the package without asking the app: a
 * date that is not `YYYY-MM-DD`, more than 200 options, …), `capability`,
 * `unavailable`. **There is no `<input type="date">` or `prompt` fallback**: where it is
 * `unavailable` the page shows its own picker.
 */
export async function showPicker(options: ShowPickerOptions): Promise<ShowPickerResult> {
  const problem = pickerProblem(options)
  if (problem) return invalid('showPicker', problem)
  const answer = await callFeature('pickers', 'showPicker', { ...options })
  if (!answer.ok) return asFailure(answer)
  const { value } = answer as { value?: unknown }
  return typeof value === 'string' ? { ok: true, value } : badAnswer()
}
