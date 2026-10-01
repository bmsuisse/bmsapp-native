import { isNativeApp, post } from './bridge.js'

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
  /** Height in points (24–120), default 44. */
  height?: number
  /** Text for VoiceOver. */
  alt?: string
}

export type ActionButton = { id: string; icon: string; label?: string }

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
}

/**
 * Native chrome (menu, action buttons, bottom bar) for this web app.
 * Taps arrive via `on('menuSelect' | 'actionButtonTap' | 'bottomBarTap')`.
 * No-op outside the app.
 */
export function setChrome(chrome: Chrome): void {
  if (!isNativeApp()) return
  post('setChrome', chrome)
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
