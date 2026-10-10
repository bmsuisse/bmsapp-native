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

// --- Form fields -------------------------------------------------------------
// The same fields are used by the forms of `action` widgets and by the native
// forms that a page opens with `showForm` (docs/native-surfaces-guide.md). An
// older app shows a type it does not know as `text`.

type FieldBase = {
  /** Unique within the form (also across pages). It is the key in the result `values`. */
  id: string
  label?: string
  placeholder?: string
  /** Footnote under the field. */
  help?: string
  required?: boolean
  /** Only show the field if another field of the form has a matching value. */
  visibleIf?: ActionCondition
}

/** Validation of text input. An invalid field is marked inline and blocks "Continue"/submit. */
type TextRules = {
  minLength?: number
  maxLength?: number
  /** Regular expression the whole input has to match. */
  pattern?: string
  /** Shown instead of the standard message when `pattern` does not match. */
  patternMessage?: string
}

type NumberRules = { min?: number; max?: number }

/** `value` of the fields that exist since the first schema: loosely typed, as before. */
type LooseValue = string | number | boolean

// existing types

/** Single-line text. Without `type` a field is a text field. */
export type ActionTextField = FieldBase & TextRules & { type?: 'text'; value?: LooseValue }
export type ActionNumberField = FieldBase & NumberRules & { type: 'number'; value?: LooseValue }
export type ActionSelectField = FieldBase & {
  type: 'select'
  /** Fixed choices. Ignored with `remote`. */
  options?: ActionOption[]
  /** Load the options from `widgetOptionsPath` when the field is shown. */
  remote?: boolean
  value?: LooseValue
  /** `remote` only: display text for the prefilled `value`. */
  valueLabel?: string
}
export type ActionToggleField = FieldBase & { type: 'toggle'; value?: LooseValue }
/** Date as `yyyy-MM-dd`. */
export type ActionDateField = FieldBase & { type: 'date'; value?: LooseValue }
export type ActionSearchField = FieldBase & {
  type: 'search'
  /** From this many characters on the app searches; 0 loads suggestions on open. Default 2. */
  minQueryLength?: number
  value?: LooseValue
  /** Display text for the prefilled `value`. */
  valueLabel?: string
}

// new types

/** Multi-line text; `maxLength` shows a counter. */
export type ActionTextareaField = FieldBase & TextRules & { type: 'textarea'; value?: string }
/** Text with the email keyboard and a format check. */
export type ActionEmailField = FieldBase & TextRules & { type: 'email'; value?: string }
/** Text with the phone keyboard. */
export type ActionPhoneField = FieldBase & TextRules & { type: 'phone'; value?: string }
/** Text with the URL keyboard and a format check. */
export type ActionUrlField = FieldBase & TextRules & { type: 'url'; value?: string }
/** Choose any number of `options`. Result: `string[]` of the option values. */
export type ActionMultiselectField = FieldBase & {
  type: 'multiselect'
  options: ActionOption[]
  value?: string[]
}
/** A few `options` as a segmented control. */
export type ActionSegmentedField = FieldBase & {
  type: 'segmented'
  options: ActionOption[]
  value?: string
}
/** Whole number with + and −. */
export type ActionStepperField = FieldBase &
  NumberRules & { type: 'stepper'; step?: number; value?: number }
/** Time of day as `HH:mm`. */
export type ActionTimeField = FieldBase & { type: 'time'; value?: string }
/** `yyyy-MM-ddTHH:mm`, local time of the device, no time zone. */
export type ActionDateTimeField = FieldBase & { type: 'datetime'; value?: string }
/** Read-only row (`label`, `value`). Not part of the result. */
export type ActionInfoField = FieldBase & { type: 'info'; value?: string }
/**
 * Photos from the camera and/or the library. Result: `NativeFileRef[]` (the app
 * uploads the files itself, see the guide). The camera needs `camera`.
 */
export type ActionPhotoField = FieldBase & {
  type: 'photo'
  /** How many pictures at most, 1…10. Default 5. */
  max?: number
  /** Default `both`. */
  source?: 'camera' | 'library' | 'both'
  /** Longest side in pixels after downscaling, 256…4096, default 2048. */
  maxDimension?: number
}
/** Document scanner. Result: `NativeFileRef[]`. Needs `camera`. */
export type ActionScanField = FieldBase & {
  type: 'scan'
  /** `jpeg` (default): one file per page. `pdf`: one file. */
  format?: 'jpeg' | 'pdf'
  /** How many pages at most, 1…20. Default 10. */
  max?: number
}
/** Signature drawn with finger or pencil. Result: `NativeFileRef[]` with one PNG. */
export type ActionSignatureField = FieldBase & { type: 'signature' }
/** The symbologies a `barcode` field can be restricted to. */
export type BarcodeSymbology =
  | 'aztec'
  | 'codabar'
  | 'code39'
  | 'code93'
  | 'code128'
  | 'dataMatrix'
  | 'ean8'
  | 'ean13'
  | 'i2of5'
  | 'itf14'
  | 'pdf417'
  | 'qr'
  | 'upce'

/** Text field with a button that scans a barcode/QR code. Needs `camera`. */
export type ActionBarcodeField = FieldBase &
  TextRules & {
    type: 'barcode'
    /** Restrict the scanner to these symbologies. Default: all of them. */
    symbologies?: BarcodeSymbology[]
    value?: string
  }

/**
 * The field types that can be used inside a `repeat` group. They cannot be
 * conditional: no `visibleIf` inside a group.
 */
export type ActionRepeatInnerField =
  | Omit<ActionTextField, 'visibleIf'>
  | Omit<ActionNumberField, 'visibleIf'>
  | Omit<ActionSelectField, 'visibleIf'>
  | Omit<ActionToggleField, 'visibleIf'>
  | Omit<ActionDateField, 'visibleIf'>
  | Omit<ActionTextareaField, 'visibleIf'>
  | Omit<ActionStepperField, 'visibleIf'>

/**
 * Repeating group (for example order lines). Result: an array of objects, one per
 * row, keyed by the ids of the inner `fields`. No nesting.
 */
export type ActionRepeatField = FieldBase & {
  type: 'repeat'
  fields: ActionRepeatInnerField[]
  /** Fewest rows, default 0. */
  min?: number
  /** Most rows, at most 50. */
  max?: number
  /** Label of the "add row" button. */
  addLabel?: string
  value?: Array<Record<string, unknown>>
}

export type ActionField =
  | ActionTextField
  | ActionNumberField
  | ActionSelectField
  | ActionToggleField
  | ActionDateField
  | ActionSearchField
  | ActionTextareaField
  | ActionEmailField
  | ActionPhoneField
  | ActionUrlField
  | ActionMultiselectField
  | ActionSegmentedField
  | ActionStepperField
  | ActionTimeField
  | ActionDateTimeField
  | ActionInfoField
  | ActionPhotoField
  | ActionScanField
  | ActionSignatureField
  | ActionBarcodeField
  | ActionRepeatField

/** The `type` of a field; a field without `type` is `text`. */
export type ActionFieldType = NonNullable<ActionField['type']> | 'text'

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
