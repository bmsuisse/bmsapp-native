// Dashboard widgets (schema v1). Mirrored by hand from
// `bmsdna.app_native.widgets` — always change both sides; the shared
// examples in `contract-fixtures/` check that both match.
// Details: docs/dashboard-widgets-guide.md

import { call, type NativeResult } from './bridge.js'

/** The app formats numbers according to the device language; strings appear unchanged. */
export type Value = string | number

export type Trend = {
  direction?: 'up' | 'down' | 'flat'
  text?: string
  /** Whether the direction is "good" (green). Default: up = good. */
  positive?: boolean
}

export type WidgetButton = {
  id: string
  label: string
  style?: 'primary' | 'secondary' | 'destructive'
  icon?: string
  /** Confirmation prompt before running. */
  confirm?: string
  /** Confirm with Face ID first (UX only, no proof for the backend). */
  biometric?: boolean
}

export type KpiData = { value: Value; unit?: string; caption?: string; trend?: Trend }

export type StatItem = { label: string; value: Value; trend?: Trend }
export type StatsData = { items: StatItem[] }

export type ListItem = {
  id: string
  title: string
  subtitle?: string
  trailing?: Value
  icon?: string
  tint?: string
  path?: string
  actions?: WidgetButton[]
}
export type ListData = { items?: ListItem[]; maxVisible?: number; emptyText?: string }

export type ChartPoint = { x: Value; y: number }
export type ChartSeries = { name?: string; color?: string; points: ChartPoint[] }
export type ChartData = { type?: 'bar' | 'line' | 'area'; series: ChartSeries[]; unit?: string }

export type ProgressData = {
  value: number
  total?: number
  caption?: string
  style?: 'bar' | 'ring'
}

export type TextData = { markdown: string; linkLabel?: string }

export type NewsItem = {
  id: string
  title: string
  text?: string
  imageUrl?: string
  path?: string
  /** ISO 8601 with time zone. */
  date?: string
  caption?: string
  channels?: string[]
}
export type NewsData = { items?: NewsItem[]; emptyText?: string }

export type ActionOption = { value: string; label?: string; subtitle?: string }

type ConditionValue = string | number | boolean
export type ActionCondition = { field: string; equals?: ConditionValue | ConditionValue[] }

export type ActionField = {
  id: string
  type?: 'text' | 'number' | 'select' | 'toggle' | 'date' | 'search'
  label?: string
  placeholder?: string
  options?: ActionOption[]
  remote?: boolean
  minQueryLength?: number
  required?: boolean
  visibleIf?: ActionCondition
  value?: string | number | boolean
  valueLabel?: string
}

export type ActionPage = { title?: string; text?: string; fields: ActionField[] }

export type ActionData = {
  text?: string
  fields?: ActionField[]
  pages?: ActionPage[]
  buttons: WidgetButton[]
}

type WidgetBase = {
  /** Keep it stable; the app uses it to remember order and visibility. No `/`. */
  id: string
  size?: 'small' | 'medium' | 'large' | 'tall' | 'xlarge'
  title?: string
  icon?: string
  tint?: string
  required?: boolean
  defaultEnabled?: boolean
  path?: string
  /** ISO 8601 with time zone. */
  updatedAt?: string
  /** ISO 8601 with time zone. */
  expiresAt?: string
}

export type Widget = WidgetBase &
  (
    | { kind: 'kpi'; data: KpiData }
    | { kind: 'stats'; data: StatsData }
    | { kind: 'list'; data: ListData }
    | { kind: 'chart'; data: ChartData }
    | { kind: 'progress'; data: ProgressData }
    | { kind: 'text'; data: TextData }
    | { kind: 'action'; data: ActionData }
    | { kind: 'news'; data: NewsData }
  )

export type WidgetKind = Widget['kind']

/** Replaces ALL widgets of this web app. The app discards invalid ones individually. Requires `dashboardWidgets`. */
export function setWidgets(
  widgets: Widget[]
): Promise<NativeResult<{ accepted: number; rejected: number }>> {
  return call('setWidgets', { widgets })
}

/** Replaces a widget (same `id`) or appends it. */
export function updateWidget(widget: Widget): Promise<NativeResult> {
  return call('updateWidget', { widget })
}

/** Removes the given widgets; without `ids`, all of this web app's widgets. */
export function removeWidgets(ids?: string[]): Promise<NativeResult> {
  return call('removeWidgets', ids ? { ids } : {})
}

/** Natively reloads the widget feed (`widgetFeedPath`) right away. */
export function refreshWidgets(): Promise<NativeResult> {
  return call('refreshWidgets')
}
