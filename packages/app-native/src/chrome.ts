import { can, hasFeature, isNativeApp, post, type Feature } from './bridge.js'
import { isDevelopment, warn } from './dev.js'
import { isRecord, nonEmptyString } from './internal.js'
import { menuLimitWarnings, type NativeMenuSection } from './menus.js'

export type MenuItem = {
  id: string
  label: string
  /** SF Symbol name, e.g. `"plus.circle"`. */
  icon?: string
  destructive?: boolean
  /** Hex color for icon and text; ignored with `destructive`. */
  color?: string
  /** Right-aligned grey value at the end of the row, e.g. a count. */
  value?: string
  /** `false` keeps the item out of iOS Search/Siri (default: included, except `destructive`). */
  searchable?: boolean
}

export type MenuSection = { title?: string; items: MenuItem[] }

/** Custom header at the top of the menu. Exactly one of `logo`, `html`, `image`. */
export type MenuHeader = (
  | { logo: 'one'; suffix?: string }
  | { html: string; css?: string }
  | { image: string }
) & {
  /**
   * Design height in points (24–120), default 44. A taller logo is scaled down to the
   * maximum height of the bar. The header sits flush left in the top bar of the menu, in
   * place of the web app's name.
   */
  height?: number
  /** Text for VoiceOver. */
  alt?: string
}

export type ActionButton = {
  id: string
  icon: string
  label?: string
  /**
   * A pull-down menu: the tap opens it instead of firing `actionButtonTap`. A selection
   * arrives as `on('actionButtonMenuSelect', ({ buttonId, id }) => …)`. Feature `menus`;
   * an app without it ignores `menu` and fires `actionButtonTap`.
   */
  menu?: NativeMenuSection[]
}

/** The native navigation title (feature `titleMenu`). */
export type ChromeTitle = {
  /** Shown instead of the web app's name. Shown as delivered. */
  text: string
  subtitle?: string
  /**
   * Makes the title a **title menu**; a selection arrives as
   * `on('titleMenuSelect', ({ id }) => …)`.
   */
  menu?: NativeMenuSection[]
}

/** The native search field in the navigation bar (feature `navSearch`). */
export type ChromeSearch = {
  /** Comes back in the events. */
  id: string
  placeholder: string
  /** The text in the field. */
  value?: string
  /** A scope bar under the field. */
  scopes?: Array<{ id: string; label: string }>
  /** The selected scope; default the first. */
  scope?: string
  /** Adds a scan button (needs `camera`); the code arrives with `source: 'barcode'`. */
  barcode?: boolean
}

/** Segments under the navigation bar (feature `segments`): 2 to 5 items. */
export type ChromeSegments = {
  id: string
  items: Array<{ id: string; label: string; /** A short string. */ badge?: string }>
  /** The `id` of the selected item. */
  selected: string
}

export type SidebarAction = {
  id: string
  label: string
  style?: 'default' | 'destructive'
  /** SF Symbol. */
  icon?: string
}

export type SidebarItem = {
  id: string
  label: string
  subtitle?: string
  /** SF Symbol. */
  icon?: string
  badge?: string
  selected?: boolean
  /** Swipe actions; they arrive as `on('sidebarAction', ({ itemId, id }) => …)`. */
  trailingActions?: SidebarAction[]
}

export type SidebarSection = { title?: string; items: SidebarItem[] }

/**
 * The iPad sidebar (feature `sidebar`): a collapsible native column to the left of the
 * web view, **only in the regular horizontal size class** (in compact width it is
 * ignored and the page shows its own list). At most 300 items.
 */
export type ChromeSidebar = {
  title: string
  search?: { placeholder: string }
  sections: SidebarSection[]
  footer?: string
}

/** Undo and redo (feature `undoGestures`): shake, the iPad gestures and the edit menu. */
export type ChromeUndo = {
  canUndo: boolean
  canRedo: boolean
  /** What iOS shows as the name of the action ("Undo Delete Line"). Shown as delivered. */
  undoLabel?: string
  redoLabel?: string
}

/** Limits of the 2026-11b parts of `setChrome`. */
export const CHROME_LIMITS = {
  segments: { min: 2, max: 5 },
  sidebarItems: 300,
  /** Swipe actions of one sidebar item. */
  sidebarActions: 3,
  /** Items of the sidebar that are `selected`. */
  sidebarSelected: 1,
} as const

export type BottomBarItem = {
  id: string
  icon: string
  label: string
  badge?: number
  /** Only with `bottomBarStyle: 'prominent'`: raised center button. */
  prominent?: boolean
}

export type BottomBarStyle = 'normal' | 'prominent' | 'hidden' | 'none'

export type Chrome = {
  /**
   * How long the chrome applies: `page` (default) until the next real
   * navigation, `route` additionally until the next SPA route change,
   * `app` until the web app itself sends a new one.
   */
  scope?: 'page' | 'route' | 'app'
  /** Requires `customChrome`. */
  menu?: MenuSection[]
  /** Requires `customChrome`. */
  menuHeader?: MenuHeader
  /** Requires `customChrome`; at most 2. */
  actionButtons?: ActionButton[]
  /** Requires `customBottomBar`; at most 5. */
  bottomBar?: BottomBarItem[]
  bottomBarStyle?: BottomBarStyle
  /** Hex color of the bottom bar. */
  bottomBarColor?: string
  /** Requires `customChrome` and the feature `titleMenu`. */
  title?: ChromeTitle
  /** Requires `customChrome` and the feature `navSearch`. Omitting it removes the field. */
  search?: ChromeSearch
  /** Requires `customChrome` and the feature `segments`. Omitting it removes them. */
  segments?: ChromeSegments
  /** Requires `customChrome` and the feature `sidebar`. Sending it again replaces the content. */
  sidebar?: ChromeSidebar
  /** Requires `customChrome` and the feature `undoGestures`. Omitting it disables them. */
  undo?: ChromeUndo
}

const FEATURE_OF_KEY: Array<[keyof Chrome, Feature]> = [
  ['title', 'titleMenu'],
  ['search', 'navSearch'],
  ['segments', 'segments'],
  ['sidebar', 'sidebar'],
  ['undo', 'undoGestures'],
]

function prefixed(where: string, problems: string[]): string[] {
  return problems.map((p) => `${where}: ${p}`)
}

function hasLazy(sections: unknown): boolean {
  if (!Array.isArray(sections)) return false
  return sections.some(
    (section) =>
      isRecord(section) &&
      Array.isArray(section.items) &&
      section.items.some(
        (item) => isRecord(item) && (item.children === 'lazy' || hasLazy(item.children))
      )
  )
}

/** The menus of the navigation bar: the limits of `showMenu`, and no lazy items (no `menuId` to answer). */
function barMenuWarnings(where: string, menu: unknown): string[] {
  const warnings = prefixed(where, menuLimitWarnings(menu as NativeMenuSection[]))
  if (hasLazy(menu)) {
    warnings.push(`${where}: children: "lazy" only works with showMenu, give the sections.`)
  }
  return warnings
}

function searchWarnings(search: unknown): string[] {
  if (!isRecord(search)) return ['search has to be an object.']
  const warnings: string[] = []
  if (!nonEmptyString(search.id)) warnings.push('search.id has to be a non-empty string.')
  if (typeof search.placeholder !== 'string')
    warnings.push('search.placeholder has to be a string.')
  if (search.value !== undefined && typeof search.value !== 'string') {
    warnings.push('search.value has to be a string.')
  }
  const { scopes } = search
  if (scopes !== undefined) {
    if (
      !Array.isArray(scopes) ||
      scopes.some((s) => !isRecord(s) || !nonEmptyString(s.id) || typeof s.label !== 'string')
    ) {
      warnings.push('search.scopes needs entries with an id and a label.')
    } else {
      const ids = scopes.map((s: { id: string }) => s.id)
      if (new Set(ids).size !== ids.length) warnings.push('search.scopes: ids are not unique.')
      if (search.scope !== undefined && !ids.includes(search.scope as string)) {
        warnings.push(`search.scope "${String(search.scope)}" is not one of the scopes.`)
      }
    }
  } else if (search.scope !== undefined) {
    warnings.push('search.scope is given but there are no scopes.')
  }
  if (search.barcode !== undefined && typeof search.barcode !== 'boolean') {
    warnings.push('search.barcode has to be a boolean.')
  }
  if (search.barcode === true && isNativeApp() && !can('camera')) {
    warnings.push('search.barcode needs the capability camera.')
  }
  return warnings
}

function segmentsWarnings(segments: unknown): string[] {
  if (!isRecord(segments)) return ['segments has to be an object.']
  const warnings: string[] = []
  if (!nonEmptyString(segments.id)) warnings.push('segments.id has to be a non-empty string.')
  const { items } = segments
  if (!Array.isArray(items)) return [...warnings, 'segments.items has to be a list.']
  const { min, max } = CHROME_LIMITS.segments
  if (items.length < min || items.length > max) {
    warnings.push(`segments has ${items.length} items, the app takes ${min} to ${max}.`)
  }
  const ids: string[] = []
  for (const [i, item] of items.entries()) {
    if (!isRecord(item) || !nonEmptyString(item.id) || typeof item.label !== 'string') {
      warnings.push(`segments.items[${i}] needs an id and a label.`)
      continue
    }
    ids.push(item.id)
    if (item.badge !== undefined && typeof item.badge !== 'string') {
      warnings.push(`segments.items[${i}].badge has to be a short string.`)
    }
  }
  if (new Set(ids).size !== ids.length) warnings.push('segments.items: ids are not unique.')
  if (!ids.includes(segments.selected as string)) {
    warnings.push(`segments.selected "${String(segments.selected)}" is not one of the items.`)
  }
  return warnings
}

function sidebarWarnings(sidebar: unknown): string[] {
  if (!isRecord(sidebar)) return ['sidebar has to be an object.']
  const warnings: string[] = []
  if (typeof sidebar.title !== 'string') warnings.push('sidebar.title has to be a string.')
  if (sidebar.footer !== undefined && typeof sidebar.footer !== 'string') {
    warnings.push('sidebar.footer has to be a string.')
  }
  if (
    sidebar.search !== undefined &&
    !(isRecord(sidebar.search) && typeof sidebar.search.placeholder === 'string')
  ) {
    warnings.push('sidebar.search needs a placeholder.')
  }
  const { sections } = sidebar
  if (!Array.isArray(sections)) return [...warnings, 'sidebar.sections has to be a list.']
  let count = 0
  let selected = 0
  for (const [s, section] of sections.entries()) {
    if (!isRecord(section) || !Array.isArray(section.items)) {
      warnings.push(`sidebar.sections[${s}] needs a list of items.`)
      continue
    }
    for (const [i, item] of section.items.entries()) {
      count += 1
      const at = `sidebar.sections[${s}].items[${i}]`
      if (!isRecord(item) || !nonEmptyString(item.id) || typeof item.label !== 'string') {
        warnings.push(`${at} needs an id and a label.`)
        continue
      }
      if (item.selected === true) selected += 1
      const actions = Array.isArray(item.trailingActions) ? item.trailingActions : []
      if (actions.length > CHROME_LIMITS.sidebarActions) {
        warnings.push(
          `${at} has ${actions.length} swipe actions, the app takes at most ${CHROME_LIMITS.sidebarActions}.`
        )
      }
      for (const [a, action] of actions.entries()) {
        if (!isRecord(action) || !nonEmptyString(action.id) || typeof action.label !== 'string') {
          warnings.push(`${at}.trailingActions[${a}] needs an id and a label.`)
        }
      }
    }
  }
  if (count > CHROME_LIMITS.sidebarItems) {
    warnings.push(
      `sidebar has ${count} items, the app takes at most ${CHROME_LIMITS.sidebarItems}.`
    )
  }
  if (selected > CHROME_LIMITS.sidebarSelected) {
    warnings.push(`sidebar has ${selected} selected items, the app takes at most one.`)
  }
  return warnings
}

function undoWarnings(undo: unknown): string[] {
  if (!isRecord(undo)) return ['undo has to be an object.']
  const warnings: string[] = []
  for (const key of ['canUndo', 'canRedo'] as const) {
    if (typeof undo[key] !== 'boolean') warnings.push(`undo.${key} has to be a boolean.`)
  }
  for (const key of ['undoLabel', 'redoLabel'] as const) {
    if (undo[key] !== undefined && typeof undo[key] !== 'string')
      warnings.push(`undo.${key} has to be a string.`)
  }
  return warnings
}

function titleWarnings(title: unknown): string[] {
  if (!isRecord(title)) return ['title has to be an object.']
  const warnings: string[] = []
  if (!nonEmptyString(title.text)) warnings.push('title.text has to be a non-empty string.')
  if (title.subtitle !== undefined && typeof title.subtitle !== 'string') {
    warnings.push('title.subtitle has to be a string.')
  }
  if (title.menu !== undefined) warnings.push(...barMenuWarnings('title.menu', title.menu))
  return warnings
}

/**
 * Checks the 2026-11b parts of a `setChrome` payload (`actionButtons[].menu`, `title`,
 * `search`, `segments`, `sidebar`, `undo`) against the limits of the app and returns one
 * sentence per problem; empty means fine. `setChrome` logs these in development
 * builds; the app ignores what it cannot use.
 */
export function chromeLimitWarnings(chrome: Chrome): string[] {
  const warnings: string[] = []
  const buttons = chrome.actionButtons
  if (Array.isArray(buttons)) {
    buttons.forEach((button, i) => {
      if (button?.menu !== undefined && button.menu !== null) {
        warnings.push(...barMenuWarnings(`actionButtons[${i}].menu`, button.menu))
      }
    })
  }
  if (chrome.title !== undefined) warnings.push(...titleWarnings(chrome.title))
  if (chrome.search !== undefined) warnings.push(...searchWarnings(chrome.search))
  if (chrome.segments !== undefined) warnings.push(...segmentsWarnings(chrome.segments))
  if (chrome.sidebar !== undefined) warnings.push(...sidebarWarnings(chrome.sidebar))
  if (chrome.undo !== undefined) warnings.push(...undoWarnings(chrome.undo))
  return warnings
}

/** Keys of `chrome` that need a feature the app does not list (development hint). */
function missingFeatures(chrome: Chrome): string[] {
  const missing = FEATURE_OF_KEY.filter(
    ([key, feature]) => chrome[key] !== undefined && !hasFeature(feature)
  ).map(
    ([key, feature]) =>
      `\`${key}\` needs the feature ${feature}, which this app does not list: it ignores it.`
  )
  if (chrome.actionButtons?.some((b) => b.menu !== undefined) && !hasFeature('menus')) {
    missing.push(
      '`actionButtons[].menu` needs the feature menus, which this app does not list: it fires actionButtonTap.'
    )
  }
  return missing
}

/**
 * What the app can take of `chrome`: parts whose feature the app does not list are left out
 * (it would ignore them anyway), and so are menus with lazy items in the navigation bar (only
 * `showMenu` can answer a lazy item). Returns `null` if nothing is left of a chrome that
 * consisted of such parts only.
 */
function supportedChrome(chrome: Chrome): Chrome | null {
  const copy: Chrome = { ...chrome }
  for (const [key, feature] of FEATURE_OF_KEY) {
    if (copy[key] !== undefined && !hasFeature(feature)) delete copy[key]
  }
  if (copy.title?.menu !== undefined && hasLazy(copy.title.menu)) {
    const { menu: _menu, ...title } = copy.title
    copy.title = title
  }
  if (Array.isArray(copy.actionButtons)) {
    copy.actionButtons = copy.actionButtons.map((button) => {
      if (button?.menu === undefined) return button
      if (hasFeature('menus') && !hasLazy(button.menu)) return button
      const { menu: _menu, ...rest } = button
      return rest
    })
  }
  const dropped = Object.keys(chrome).length > 0 && Object.keys(copy).length === 0
  return dropped ? null : copy
}

/**
 * Native chrome (menu, action buttons, bottom bar, and since 2026-11b the title, search
 * field, segments, iPad sidebar and undo) for this web app. Taps arrive via
 * `on('menuSelect' | 'actionButtonTap' | 'bottomBarTap' | 'actionButtonMenuSelect' |
 * 'titleMenuSelect' | 'search' | 'searchCancel' | 'segmentSelect' | 'sidebarSelect' |
 * 'sidebarAction' | 'sidebarSearch' | 'undo')`.
 *
 * No-op outside the app, so the 2026-11b additions are simply ignored in the browser:
 * keep your own UI for them (`hasFeature('navSearch')` and friends tell whether the app
 * draws them). **A part whose feature the app does not list is not sent**, and neither is a
 * menu of the bar that contains `children: 'lazy'` (that only works with `showMenu`);
 * a button whose menu is left out fires `actionButtonTap`. Omitting `search`, `segments`,
 * `sidebar` or `undo` removes it again. In development builds the limits of the additions
 * are checked (`chromeLimitWarnings`) and what is left out is reported.
 */
export function setChrome(chrome: Chrome): void {
  if (!isNativeApp()) return
  if (isDevelopment())
    warn('setChrome', [...chromeLimitWarnings(chrome), ...missingFeatures(chrome)])
  const supported = supportedChrome(chrome)
  if (supported) post('setChrome', supported)
}

/**
 * Marks the entry `prominentId` as `prominent` and moves it to the middle
 * (`Math.floor(length / 2)`, the same formula as the app), so the raised
 * center button stays centered no matter how many entries are visible.
 * If `prominentId` is not found, the array is returned unchanged.
 */
export function centerProminentEntry<T extends { id: string }>(
  entries: T[],
  prominentId: string
): Array<T & { prominent?: boolean }> {
  const entry = entries.find((e) => e.id === prominentId)
  if (!entry) return entries
  const rest = entries.filter((e) => e !== entry)
  const middle = Math.floor(entries.length / 2)
  return [...rest.slice(0, middle), { ...entry, prominent: true }, ...rest.slice(middle)]
}
