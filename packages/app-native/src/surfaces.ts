// Native surfaces: forms and content that the page opens as native iOS sheets
// (`showForm`, `showContent`), with an optional round trip to the page.
// Mirrored by hand from `bmsdna.app_native.surfaces` — always change both
// sides; the shared examples in `contract-fixtures/` check that both match.
// Details: docs/native-surfaces-guide.md

import { call, can, type NativeResult } from './bridge.js'
import type {
  AddReminderPayload,
  CallPhonePayload,
  NavigatePayload,
  SaveContactPayload,
} from './deviceActions.js'
import { isDevelopment, warn } from './dev.js'
import { on } from './events.js'
import type { ActionField, ChartData, KpiData, ProgressData, StatsData, Value } from './widgets.js'

// --- Common ------------------------------------------------------------------

/**
 * Why a surface call failed. An app that predates the feature answers
 * `unknownAction`, an app without the capability `capability`: treat both,
 * like `unavailable`, as "use your own web UI" (see `isNativeSurfaceUnsupported`).
 *
 * - `invalid`: the definition does not parse; `message` names the field path.
 * - `forbidden`: not the main frame on the web app's own origin.
 * - `busy`: a surface of this web app is already open (one at a time).
 * - `tooLarge`: a limit was exceeded (`NATIVE_SURFACE_LIMITS`).
 * - `cancelled`: the user dismissed the surface, or `closeSurface` closed it.
 * - `unavailable`: nothing to present on right now, the camera is missing, or the
 *   page runs outside the app. Also: the app wanted to call the page and found
 *   no `onNativeSurfaceAction`.
 */
export type NativeSurfaceError =
  | 'invalid'
  | 'capability'
  | 'forbidden'
  | 'busy'
  | 'tooLarge'
  | 'cancelled'
  | 'unavailable'
  | 'unknownAction'
  | 'failed'

export type NativeSurfaceFailure = {
  ok: false
  error: NativeSurfaceError
  /** Developer-facing, English. */
  message?: string
}

/**
 * How big the sheet is: `full` is a full-screen cover, `large` and `medium` are
 * the standard iOS sheet detents (`medium` can be pulled up), `fit` is a sheet
 * exactly as high as its content (at most `large`). On iPad: a centered sheet.
 */
export type SurfaceSize = 'full' | 'large' | 'medium' | 'fit'

/**
 * A file the app has already uploaded to your backend's document router. The
 * file content never passes through the page: you only get this reference and
 * send it to your own backend as part of your normal request.
 */
export type NativeFileRef = {
  name: string
  mime: string
  size: number
  /** The `id` your document router answered with, otherwise the `upload_id`. */
  ref: string
}

export type NativeSurfaceCommon = {
  /**
   * Echoed in results and events; used by `closeSurface` and `surfaceResult`.
   * The app generates one if missing (the `onSubmit`/`onAction` helpers do it for you).
   */
  id?: string
  /** Title in the navigation bar. */
  title?: string
  /** Forms default to `large`, content to `medium`. */
  size?: SurfaceSize
  /** Accent color, `#rrggbb`. */
  tint?: string
  /** Opaque to the app; echoed in results and events and sent along with option lookups. */
  context?: Record<string, unknown>
}

// --- Forms -------------------------------------------------------------------

/** Same fields as the forms of `action` widgets, plus the new types. */
export type NativeFormField = ActionField

export type NativeFormPage = { title?: string; text?: string; fields: NativeFormField[] }

export type NativeFormSubmit = {
  /** Label of the submit button. */
  label?: string
  /** Confirmation prompt before submitting. */
  confirm?: string
  /** Confirm with Face ID first (UX only, no proof for the backend). */
  biometric?: boolean
  style?: 'primary' | 'destructive'
  /**
   * Round trip: keep the form open with a spinner until the page answers with
   * `surfaceResult` (the `onSubmit` helper of `showForm` sets this for you).
   */
  wait?: boolean
}

export type NativeFormDef = NativeSurfaceCommon & {
  /** Intro text on the first page. */
  text?: string
  /** Prefill by field id. */
  values?: Record<string, unknown>
  /** Single-page form. For several pages use `pages` (not both). */
  fields?: NativeFormField[]
  pages?: NativeFormPage[]
  submit?: NativeFormSubmit
}

/**
 * What a submitted form delivers: numbers as numbers, toggles as booleans, dates
 * `yyyy-MM-dd`; empty and hidden fields are left out.
 */
export type NativeFormValue =
  | string
  | number
  | boolean
  | string[]
  | NativeFileRef[]
  | Array<Record<string, unknown>>

export type NativeFormValues = Record<string, NativeFormValue>

export type NativeFormResult =
  | {
      ok: true
      id: string
      action: 'submit'
      values: NativeFormValues
      /** The text shown for `search`/`select` fields, by field id. */
      labels: Record<string, string>
      context?: Record<string, unknown>
      /** The result of the last surface of a chained flow. */
      next?: NativeSurfaceResult
    }
  | NativeSurfaceFailure

// --- Content -----------------------------------------------------------------

/** Follow-up of an action; runs in the app before the call resolves. */
export type NativeThen =
  /** Open this path in the web app. */
  | { openPath: string }
  /** Open this URL outside the app. */
  | { openUrl: string }
  | { copy: string }
  | { share: { text?: string; url?: string } }
  | { close: true }
  /** One of the device actions, with the same payload (see device-actions-guide.md). */
  | { device: NativeDeviceAction }
  /**
   * Chained flow: replaces the current surface with the next one. At most 4 after
   * the first (5 screens in a flow). Give the chained definition an explicit `id`
   * if the page wants to answer a round trip of it (`onSurfaceAction`).
   */
  | { showForm: NativeFormDef }
  | { showContent: NativeContentDef }

export type NativeDeviceAction =
  | ({ action: 'navigate' } & NavigatePayload)
  | ({ action: 'callPhone' } & CallPhonePayload)
  | ({ action: 'saveContact' } & SaveContactPayload)
  | ({ action: 'addReminder' } & AddReminderPayload)

/** A button of the content (footer `actions`, `buttons` block, row of a `list`). */
export type NativeAction = {
  /** Comes back as `action` in the result. */
  id: string
  label: string
  style?: 'primary' | 'secondary' | 'destructive'
  /** SF Symbol. */
  icon?: string
  /** Confirmation prompt before running. */
  confirm?: string
  /** Confirm with Face ID first (UX only, no proof for the backend). */
  biometric?: boolean
  /** Validate the `fields` blocks first and return their `values`. */
  submit?: boolean
  /** Round trip: keep the surface open until the page answers with `surfaceResult`. */
  wait?: boolean
  then?: NativeThen[]
}

export type NativeFact = {
  label: string
  value: string
  /** Makes the row tappable: call, mail, route, open. */
  kind?: 'text' | 'phone' | 'email' | 'address' | 'url'
  icon?: string
  copyable?: boolean
}

export type NativeListItem = {
  title: string
  subtitle?: string
  trailing?: Value
  icon?: string
  /** `https` URL. Not a `data:` URI: the app rejects those here. */
  image?: string
  action?: NativeAction
}

export type NativeTableColumn = {
  key: string
  label: string
  align?: 'leading' | 'center' | 'trailing'
}

export type NativeBadge = { text: string; tint?: string; icon?: string }

export type NativeContentBlock =
  | { type: 'heading'; text: string; level?: 1 | 2 | 3; icon?: string }
  | {
      type: 'text'
      /** Paragraphs, lists, quotes, tables, bold/italic/links. No HTML. */
      markdown: string
      style?: 'body' | 'caption' | 'footnote'
      align?: 'leading' | 'center' | 'trailing'
    }
  | {
      type: 'image'
      /** `https` URL. URLs on the web app's own backend load with its token. */
      url?: string
      /** `data:image/…`, at most 1 MB. */
      data?: string
      alt?: string
      caption?: string
      height?: number
      fit?: 'fit' | 'fill'
      shape?: 'rounded' | 'circle' | 'none'
      tapToZoom?: boolean
    }
  | { type: 'facts'; items: NativeFact[] }
  | { type: 'list'; items: NativeListItem[] }
  | {
      type: 'table'
      columns: NativeTableColumn[]
      rows: Array<Record<string, string | number>>
      caption?: string
    }
  | {
      type: 'map'
      latitude: number
      longitude: number
      name?: string
      /** Visible area in meters. */
      span?: number
      height?: number
    }
  | {
      type: 'file'
      /** Tap previews it. URLs on the web app's own backend load with its token. */
      url: string
      name?: string
      mime?: string
    }
  | { type: 'video'; url: string; poster?: string }
  | {
      type: 'callout'
      style: 'info' | 'success' | 'warning' | 'error'
      title?: string
      text: string
    }
  | { type: 'badges'; items: NativeBadge[] }
  | { type: 'buttons'; items: NativeAction[] }
  | { type: 'kpi'; data: KpiData }
  | { type: 'stats'; data: StatsData }
  | { type: 'chart'; data: ChartData }
  | { type: 'progress'; data: ProgressData }
  /** Form fields inside content; their values come back with an action that has `submit`. */
  | { type: 'fields'; fields: NativeFormField[] }
  | { type: 'card'; title?: string; blocks: NativeContentBlock[] }
  | { type: 'row'; blocks: NativeContentBlock[] }
  | { type: 'divider' }
  | { type: 'spacer'; height?: number }

export type NativeContentDef = NativeSurfaceCommon & {
  subtitle?: string
  blocks: NativeContentBlock[]
  /** Footer buttons, at most 4. */
  actions?: NativeAction[]
}

export type NativeContentResult =
  | {
      ok: true
      id: string
      /** The `id` of the tapped action, or `"dismiss"`. */
      action: string
      /** The `fields` values, if the action had `submit`. */
      values?: NativeFormValues
      next?: NativeSurfaceResult
      context?: Record<string, unknown>
    }
  | NativeSurfaceFailure

export type NativeSurfaceResult = NativeFormResult | NativeContentResult

// --- Limits ------------------------------------------------------------------

/**
 * What the app accepts. The app enforces them (a call beyond a limit answers
 * `tooLarge` or `invalid`, nothing is cut silently); `formLimitWarnings` and
 * `contentLimitWarnings` check them early.
 */
export const NATIVE_SURFACE_LIMITS = {
  /** The whole definition as JSON, in bytes. */
  definitionBytes: 256 * 1024,
  formPages: 10,
  formFields: 60,
  /** Inline `options` per field. */
  fieldOptions: 200,
  repeatRows: 50,
  /** Fields in one `repeat` group, 1 to this many (the app answers `invalid` beyond). */
  repeatFields: 10,
  /** `photo.max`. */
  photoMax: 10,
  /** `photo.maxDimension`, from and up to. */
  photoMinDimension: 256,
  photoMaxDimension: 4096,
  /** `scan.max`: pages. */
  scanMaxPages: 20,
  contentBlocks: 100,
  /** Levels of blocks, the top level counting as 1: card > card > text is fine. */
  contentNesting: 3,
  /** Items of one `buttons` block. */
  buttonsPerBlock: 6,
  /** Fields of all `fields` blocks of one content screen together. */
  contentFields: 60,
  tableColumns: 20,
  tableRows: 200,
  footerActions: 4,
  /** Steps in one `then` list (the app answers `tooLarge` beyond). */
  thenSteps: 6,
  /** One inline `data:` image, in bytes. */
  inlineImageBytes: 1024 * 1024,
  inlineImagesTotalBytes: 4 * 1024 * 1024,
  /** Chained surfaces after the first one: a flow has at most 5 screens in total. */
  chainDepth: 4,
  /** One uploaded media file after downscaling, in bytes. */
  mediaFileBytes: 25 * 1024 * 1024,
  /** All media of one form, in bytes. */
  mediaTotalBytes: 100 * 1024 * 1024,
  /** How long the page has to answer a round trip, in seconds. */
  roundTripSeconds: 60,
} as const

function byteLength(text: string): number {
  return typeof TextEncoder === 'undefined' ? text.length : new TextEncoder().encode(text).length
}

function definitionBytes(def: unknown): number {
  try {
    return byteLength(JSON.stringify(def) ?? '')
  } catch {
    return 0
  }
}

/** Decoded size of a `data:` URI. */
function dataUriBytes(uri: string): number {
  const comma = uri.indexOf(',')
  const payload = comma >= 0 ? uri.slice(comma + 1) : uri
  if (!/;base64$/i.test(uri.slice(0, Math.max(comma, 0)))) return byteLength(payload)
  const padding = /=+$/.exec(payload)?.[0].length ?? 0
  return Math.max(0, Math.floor((payload.length * 3) / 4) - padding)
}

function fieldWarnings(fields: NativeFormField[], where: string): string[] {
  const warnings: string[] = []
  fields.forEach((field, index) => {
    const at = `${where}[${index}] (${field.id})`
    const options = 'options' in field ? field.options : undefined
    if (options && options.length > NATIVE_SURFACE_LIMITS.fieldOptions) {
      warnings.push(
        `${at}: ${options.length} options, the app takes at most ${NATIVE_SURFACE_LIMITS.fieldOptions} inline. Use a search field or select with remote.`
      )
    }
    if (field.type === 'photo') {
      if (
        field.max !== undefined &&
        (field.max < 1 || field.max > NATIVE_SURFACE_LIMITS.photoMax)
      ) {
        warnings.push(
          `${at}: photo max ${field.max} is outside 1…${NATIVE_SURFACE_LIMITS.photoMax}.`
        )
      }
      if (
        field.maxDimension !== undefined &&
        (field.maxDimension < NATIVE_SURFACE_LIMITS.photoMinDimension ||
          field.maxDimension > NATIVE_SURFACE_LIMITS.photoMaxDimension)
      ) {
        warnings.push(
          `${at}: photo maxDimension ${field.maxDimension} is outside ${NATIVE_SURFACE_LIMITS.photoMinDimension}…${NATIVE_SURFACE_LIMITS.photoMaxDimension}.`
        )
      }
    }
    if (field.type === 'scan') {
      if (
        field.max !== undefined &&
        (field.max < 1 || field.max > NATIVE_SURFACE_LIMITS.scanMaxPages)
      ) {
        warnings.push(
          `${at}: scan max ${field.max} is outside 1…${NATIVE_SURFACE_LIMITS.scanMaxPages} pages.`
        )
      }
    }
    if (field.type === 'repeat') {
      if (field.max !== undefined && field.max > NATIVE_SURFACE_LIMITS.repeatRows) {
        warnings.push(
          `${at}: repeat max ${field.max} is above ${NATIVE_SURFACE_LIMITS.repeatRows} rows.`
        )
      }
      if (field.fields.length < 1 || field.fields.length > NATIVE_SURFACE_LIMITS.repeatFields) {
        warnings.push(
          `${at}: a repeat group has ${field.fields.length} fields, the app takes 1 to ${NATIVE_SURFACE_LIMITS.repeatFields}.`
        )
      }
      if (field.fields.some((inner) => (inner.type as string) === 'repeat')) {
        warnings.push(`${at}: a repeat group cannot contain another repeat group.`)
      }
    }
  })
  return warnings
}

/**
 * Checks a form definition against the limits of the app and returns one
 * sentence per problem. Empty: nothing to warn about. `showForm` logs these in
 * development builds; the app enforces the limits either way.
 */
export function formLimitWarnings(def: NativeFormDef): string[] {
  const limits = NATIVE_SURFACE_LIMITS
  const warnings: string[] = []
  const bytes = definitionBytes(def)
  if (bytes > limits.definitionBytes) {
    warnings.push(
      `The definition is ${bytes} bytes, the app takes at most ${limits.definitionBytes}.`
    )
  }
  if (def.fields && def.pages) warnings.push('Use either `fields` or `pages`, not both.')
  const pages = def.pages ?? []
  if (pages.length > limits.formPages) {
    warnings.push(`${pages.length} pages, the app takes at most ${limits.formPages}.`)
  }
  const fields = [...(def.fields ?? []), ...pages.flatMap((page) => page.fields)]
  if (fields.length > limits.formFields) {
    warnings.push(`${fields.length} fields, the app takes at most ${limits.formFields}.`)
  }
  warnings.push(...fieldWarnings(def.fields ?? [], 'fields'))
  pages.forEach((page, index) =>
    warnings.push(...fieldWarnings(page.fields, `pages[${index}].fields`))
  )
  for (const field of fields) {
    const rows = field.type === 'repeat' ? def.values?.[field.id] : undefined
    if (Array.isArray(rows) && rows.length > limits.repeatRows) {
      warnings.push(
        `values.${field.id}: ${rows.length} rows, the app takes at most ${limits.repeatRows}.`
      )
    }
  }
  return warnings
}

type ContentWalk = {
  blocks: number
  images: number[]
  /** Levels of nesting, the top level being 1. */
  maxDepth: number
  /** Fields of all `fields` blocks. */
  fields: number
  warnings: string[]
}

function walkBlocks(blocks: NativeContentBlock[], depth: number, where: string, walk: ContentWalk) {
  blocks.forEach((block, index) => {
    const at = `${where}[${index}]`
    walk.blocks += 1
    walk.maxDepth = Math.max(walk.maxDepth, depth)
    if (block.type === 'image' && block.data) {
      const size = dataUriBytes(block.data)
      walk.images.push(size)
      if (size > NATIVE_SURFACE_LIMITS.inlineImageBytes) {
        walk.warnings.push(
          `${at}: inline image is ${size} bytes, the app takes at most ${NATIVE_SURFACE_LIMITS.inlineImageBytes}. Use \`url\`.`
        )
      }
    }
    if (block.type === 'fields') {
      walk.fields += block.fields.length
      walk.warnings.push(...fieldWarnings(block.fields, `${at}.fields`))
    }
    if (block.type === 'buttons' && block.items.length > NATIVE_SURFACE_LIMITS.buttonsPerBlock) {
      walk.warnings.push(
        `${at}: ${block.items.length} buttons, the app takes at most ${NATIVE_SURFACE_LIMITS.buttonsPerBlock} in one block.`
      )
    }
    if (block.type === 'table') {
      if (block.columns.length > NATIVE_SURFACE_LIMITS.tableColumns) {
        walk.warnings.push(
          `${at}: ${block.columns.length} columns, the app takes at most ${NATIVE_SURFACE_LIMITS.tableColumns}.`
        )
      }
      if (block.rows.length > NATIVE_SURFACE_LIMITS.tableRows) {
        walk.warnings.push(
          `${at}: ${block.rows.length} rows, the app takes at most ${NATIVE_SURFACE_LIMITS.tableRows}.`
        )
      }
    }
    if (block.type === 'card' || block.type === 'row') {
      walkBlocks(block.blocks, depth + 1, `${at}.blocks`, walk)
    }
  })
}

/** One `then` list: at most 6 steps, and the chained content inside it as well. */
function stepsWarnings(steps: NativeThen[], where: string): string[] {
  const warnings: string[] = []
  if (steps.length > NATIVE_SURFACE_LIMITS.thenSteps) {
    warnings.push(
      `${where}: ${steps.length} \`then\` steps, the app takes at most ${NATIVE_SURFACE_LIMITS.thenSteps}.`
    )
  }
  steps.forEach((step, index) => {
    if ('showContent' in step) {
      warnings.push(...thenWarnings(step.showContent, `${where}[${index}].showContent`))
    }
  })
  return warnings
}

function actionWarnings(action: NativeAction, where: string): string[] {
  return stepsWarnings(action.then ?? [], `${where} (${action.id}).then`)
}

function blockActionWarnings(blocks: NativeContentBlock[], where: string): string[] {
  const warnings: string[] = []
  blocks.forEach((block, index) => {
    const at = `${where}[${index}]`
    if (block.type === 'buttons') {
      block.items.forEach((item, i) => warnings.push(...actionWarnings(item, `${at}.items[${i}]`)))
    }
    if (block.type === 'list') {
      block.items.forEach((item, i) => {
        if (item.action) warnings.push(...actionWarnings(item.action, `${at}.items[${i}].action`))
      })
    }
    if (block.type === 'card' || block.type === 'row') {
      warnings.push(...blockActionWarnings(block.blocks, `${at}.blocks`))
    }
  })
  return warnings
}

/** The `then` lists of all actions of a content definition, and of the content chained to them. */
function thenWarnings(def: NativeContentDef, where: string): string[] {
  const prefix = where ? `${where}.` : ''
  return [
    ...(def.actions ?? []).flatMap((action, index) =>
      actionWarnings(action, `${prefix}actions[${index}]`)
    ),
    ...blockActionWarnings(def.blocks, `${prefix}blocks`),
  ]
}

/** Steps of the longest chain of `showForm`/`showContent` in `then`. */
function chainDepth(actions: NativeAction[]): number {
  let deepest = 0
  for (const action of actions) {
    for (const step of action.then ?? []) {
      if ('showForm' in step) deepest = Math.max(deepest, 1)
      if ('showContent' in step) {
        deepest = Math.max(deepest, 1 + chainDepth(contentActions(step.showContent)))
      }
    }
  }
  return deepest
}

function contentActions(def: NativeContentDef): NativeAction[] {
  const own = def.actions ?? []
  const inBlocks: NativeAction[] = []
  const visit = (blocks: NativeContentBlock[]) => {
    for (const block of blocks) {
      if (block.type === 'buttons') inBlocks.push(...block.items)
      if (block.type === 'list') {
        for (const item of block.items) if (item.action) inBlocks.push(item.action)
      }
      if (block.type === 'card' || block.type === 'row') visit(block.blocks)
    }
  }
  visit(def.blocks)
  return [...own, ...inBlocks]
}

/**
 * Checks a content definition against the limits of the app and returns one
 * sentence per problem. Empty: nothing to warn about. `showContent` logs these in
 * development builds; the app enforces the limits either way.
 */
export function contentLimitWarnings(def: NativeContentDef): string[] {
  const limits = NATIVE_SURFACE_LIMITS
  const walk: ContentWalk = { blocks: 0, images: [], maxDepth: 0, fields: 0, warnings: [] }
  const bytes = definitionBytes(def)
  if (bytes > limits.definitionBytes) {
    walk.warnings.push(
      `The definition is ${bytes} bytes, the app takes at most ${limits.definitionBytes}.`
    )
  }
  walkBlocks(def.blocks, 1, 'blocks', walk)
  if (walk.blocks > limits.contentBlocks) {
    walk.warnings.push(`${walk.blocks} blocks, the app takes at most ${limits.contentBlocks}.`)
  }
  if (walk.maxDepth > limits.contentNesting) {
    walk.warnings.push(
      `Blocks are nested ${walk.maxDepth} levels deep, the app takes at most ${limits.contentNesting} (the top level counts as 1).`
    )
  }
  if (walk.fields > limits.contentFields) {
    walk.warnings.push(
      `${walk.fields} fields in the \`fields\` blocks, the app takes at most ${limits.contentFields} together.`
    )
  }
  const total = walk.images.reduce((sum, size) => sum + size, 0)
  if (total > limits.inlineImagesTotalBytes) {
    walk.warnings.push(
      `Inline images add up to ${total} bytes, the app takes at most ${limits.inlineImagesTotalBytes}.`
    )
  }
  if ((def.actions?.length ?? 0) > limits.footerActions) {
    walk.warnings.push(
      `${def.actions?.length} footer actions, the app takes at most ${limits.footerActions}.`
    )
  }
  walk.warnings.push(...thenWarnings(def, ''))
  const chain = chainDepth(contentActions(def))
  if (chain > limits.chainDepth) {
    walk.warnings.push(
      `${chain} chained surfaces after the first one, the app takes at most ${limits.chainDepth} (${limits.chainDepth + 1} screens in a flow in total).`
    )
  }
  return walk.warnings
}

// --- Round trip --------------------------------------------------------------

/** What the app hands to `onNativeSurfaceAction` while it waits for the page. */
export type NativeSurfaceActionEvent = {
  /** The surface. */
  id: string
  /** `submit` for a form, otherwise the `id` of the tapped action. */
  action: string
  values?: NativeFormValues
  /** The shown text of `search`/`select` fields by field id, as in the result. */
  labels?: Record<string, string>
  context?: Record<string, unknown>
}

/** The answer to a round trip, sent with `surfaceResult`. */
export type SurfaceResultPayload = {
  /** The surface (`NativeSurfaceActionEvent.id`). */
  id: string
  /** `true` closes the surface and resolves `showForm`/`showContent`; `false` keeps it open. */
  ok: boolean
  /** Shown in the surface (banner or toast). */
  message?: string
  /** Marks fields by field id and jumps to the first page with an error. `ok: false` only. */
  fieldErrors?: Record<string, string>
  /** Steps to run before closing, for example a "created" card. `ok: true` only. */
  then?: NativeThen[]
}

/**
 * What an `onSubmit`/`onAction` handler may return. Nothing means success and
 * closes the surface. `{ fieldErrors }` (not empty) or `{ ok: false }` keeps the
 * surface open. A thrown error does the same, with its `message`.
 */
export type SurfaceHandlerResult =
  | void
  | undefined
  | {
      /** `false` keeps the surface open. Default: `true`, unless there are `fieldErrors`. */
      ok?: boolean
      message?: string
      fieldErrors?: Record<string, string>
      /** At most 6 steps: the app refuses more with `tooLarge`. */
      then?: NativeThen[]
    }

/** What the page's handler for a round trip looks like (`onAction`, `onSurfaceAction`). */
export type SurfaceActionHandler = (
  event: NativeSurfaceActionEvent
) => SurfaceHandlerResult | Promise<SurfaceHandlerResult>

export type ShowFormOptions = {
  /**
   * Called when the user submits (round trip). The form stays open with a spinner
   * until this settles: a normal return closes it, `{ fieldErrors }` or a thrown
   * error keeps it open and marks the fields. Answer within 60 seconds.
   */
  onSubmit?: (
    values: NativeFormValues,
    event: NativeSurfaceActionEvent
  ) => SurfaceHandlerResult | Promise<SurfaceHandlerResult>
  /** Warn about exceeded limits in the console. Default: in development builds only. */
  validate?: boolean
}

export type ShowContentOptions = {
  /**
   * Called when the user taps an action (round trip). Actions you did not give
   * `wait` or `then` themselves are set to `wait: true`, so they arrive here.
   * Answer within 60 seconds; the return value works as for `onSubmit`.
   */
  onAction?: SurfaceActionHandler
  /** Warn about exceeded limits in the console. Default: in development builds only. */
  validate?: boolean
}

type HandlerEntry = {
  handle: SurfaceActionHandler
  /** Warn about a `then` the app would refuse (development builds by default). */
  validate: boolean
  /** Counts the actions that arrived; an answer to an older one is dropped. */
  seen: number
}

// One registry per loaded copy of this package, keyed by surface id, behind the
// single `window.onNativeSurfaceAction` that `on('surfaceAction', …)` installs.
// Several copies (or versions) chain: each one only answers its own surfaces.
const handlers = new Map<string, HandlerEntry>()
let listening = false

function errorFieldErrors(error: unknown): Record<string, string> | undefined {
  const candidate = (error as { fieldErrors?: unknown } | null)?.fieldErrors
  if (!candidate || typeof candidate !== 'object') return undefined
  const entries = Object.entries(candidate).filter(
    (entry): entry is [string, string] => typeof entry[1] === 'string'
  )
  return entries.length ? Object.fromEntries(entries) : undefined
}

function answerFor(outcome: SurfaceHandlerResult): Omit<SurfaceResultPayload, 'id'> {
  if (!outcome) return { ok: true }
  const fieldErrors =
    outcome.fieldErrors && Object.keys(outcome.fieldErrors).length ? outcome.fieldErrors : undefined
  const ok = outcome.ok !== false && !fieldErrors
  return {
    ok,
    ...(outcome.message && { message: outcome.message }),
    ...(!ok && fieldErrors && { fieldErrors }),
    ...(ok && outcome.then?.length && { then: outcome.then }),
  }
}

function answerForError(error: unknown): Omit<SurfaceResultPayload, 'id'> {
  const fieldErrors = errorFieldErrors(error)
  const message =
    error instanceof Error ? error.message : typeof error === 'string' ? error : undefined
  return { ok: false, ...(message && { message }), ...(fieldErrors && { fieldErrors }) }
}

async function dispatch(event: NativeSurfaceActionEvent): Promise<void> {
  if (!event || typeof event !== 'object' || typeof event.id !== 'string') return
  const entry = handlers.get(event.id)
  if (!entry) return
  entry.seen += 1
  const mine = entry.seen
  let answer: Omit<SurfaceResultPayload, 'id'>
  try {
    answer = answerFor(await entry.handle(event))
  } catch (error) {
    answer = answerForError(error)
  }
  // The surface is gone or the user triggered the action again after the
  // app's timeout: a late answer would close or mark the wrong attempt.
  if (handlers.get(event.id) !== entry || entry.seen !== mine) return
  // The app refuses a `then` of more than 6 steps with `tooLarge` and keeps
  // waiting for an answer, so the user would watch the spinner until the timeout.
  if (entry.validate && answer.then) warn('surfaceResult', stepsWarnings(answer.then, 'then'))
  await surfaceResult({ id: event.id, ...answer })
}

function listen(): void {
  if (listening) return
  listening = true
  on('surfaceAction', (event) => {
    void dispatch(event)
  })
}

function newSurfaceId(): string {
  const crypto = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto
  if (typeof crypto?.randomUUID === 'function') return crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

async function open<R extends NativeSurfaceResult>(
  action: 'showForm' | 'showContent',
  payload: NativeFormDef | NativeContentDef,
  handler?: SurfaceActionHandler,
  validate = false
): Promise<R> {
  if (typeof window === 'undefined' || !window.BMSNative) {
    return { ok: false, error: 'unavailable' } as R
  }
  if (!handler) return (await call(action, payload)) as unknown as R
  const id = payload.id as string
  if (handlers.has(id)) {
    return {
      ok: false,
      error: 'busy',
      message: `A surface with the id "${id}" is already open.`,
    } as R
  }
  const unregister = register(id, handler, validate)
  try {
    return (await call(action, payload)) as unknown as R
  } finally {
    unregister()
  }
}

/** Puts a handler into the registry; the returned function removes exactly this one. */
function register(id: string, handle: SurfaceActionHandler, validate: boolean): () => void {
  const entry: HandlerEntry = { handle, validate, seen: 0 }
  handlers.set(id, entry)
  listen()
  return () => {
    if (handlers.get(id) === entry) handlers.delete(id)
  }
}

// --- Calls -------------------------------------------------------------------

/**
 * Opens a native form. Requires `nativeForms` (the field types `photo` with the
 * camera, `scan` and `barcode` also `camera`). Resolves once, when the user
 * submits or dismisses it:
 *
 * ```ts
 * const res = await showForm({ title: 'New customer', fields: [...] }, {
 *   onSubmit: async (values) => { await api.post('/customers', values) },
 * })
 * ```
 *
 * Without `onSubmit` the form closes on submit and the values arrive in the
 * result; you do the request afterwards. With `onSubmit` the form stays open
 * until your handler settles, so the user can correct what the backend rejected.
 *
 * Outside the app `{ ok: false, error: 'unavailable' }`, never an exception.
 * An app without the feature answers `unknownAction` or `capability`: use
 * `isNativeSurfaceUnsupported(res)` to fall back to your own web form.
 */
export function showForm(
  def: NativeFormDef,
  options: ShowFormOptions = {}
): Promise<NativeFormResult> {
  const validate = options.validate ?? isDevelopment()
  if (validate) warn('showForm', formLimitWarnings(def))
  const { onSubmit } = options
  if (!onSubmit) return open<NativeFormResult>('showForm', def)
  const payload: NativeFormDef = {
    ...def,
    id: def.id ?? newSurfaceId(),
    submit: { ...def.submit, wait: true },
  }
  return open<NativeFormResult>(
    'showForm',
    payload,
    (event) => onSubmit(event.values ?? {}, event),
    validate
  )
}

function withWait(action: NativeAction): NativeAction {
  return action.wait === undefined && !action.then?.length ? { ...action, wait: true } : action
}

function withWaitInBlocks(blocks: NativeContentBlock[]): NativeContentBlock[] {
  return blocks.map((block): NativeContentBlock => {
    switch (block.type) {
      case 'buttons':
        return { ...block, items: block.items.map(withWait) }
      case 'list':
        return {
          ...block,
          items: block.items.map((item) =>
            item.action ? { ...item, action: withWait(item.action) } : item
          ),
        }
      case 'card':
      case 'row':
        return { ...block, blocks: withWaitInBlocks(block.blocks) }
      default:
        return block
    }
  })
}

/**
 * Opens a native content screen. Requires `nativeContent`. Resolves once, with
 * the `id` of the tapped action or `"dismiss"`.
 *
 * With `onAction` the actions call your handler and the surface stays open
 * until it settles, like `onSubmit` of `showForm`.
 *
 * Outside the app `{ ok: false, error: 'unavailable' }`, never an exception.
 */
export function showContent(
  def: NativeContentDef,
  options: ShowContentOptions = {}
): Promise<NativeContentResult> {
  const validate = options.validate ?? isDevelopment()
  if (validate) warn('showContent', contentLimitWarnings(def))
  const { onAction } = options
  if (!onAction) return open<NativeContentResult>('showContent', def)
  const payload: NativeContentDef = {
    ...def,
    id: def.id ?? newSurfaceId(),
    blocks: withWaitInBlocks(def.blocks),
    ...(def.actions && { actions: def.actions.map(withWait) }),
  }
  return open<NativeContentResult>('showContent', payload, onAction, validate)
}

/**
 * Registers the page's handler for the round trip of the surface `id`, for the
 * cases `showForm(…, { onSubmit })` and `showContent(…, { onAction })` do not
 * cover: above all a **chained** surface, which has an `id` and a round trip of
 * its own. The handler is answered like `onSubmit`/`onAction`: return nothing
 * for success, `{ fieldErrors }` or throw to keep the surface open.
 *
 * ```ts
 * const off = onSurfaceAction('reject-reason', async ({ values }) => {
 *   await api.reject(order.id, values?.reason)
 * })
 * try {
 *   await showContent({
 *     id: 'order',
 *     blocks: [...],
 *     actions: [{
 *       id: 'reject',
 *       label: 'Reject',
 *       then: [{ showForm: {
 *         id: 'reject-reason', // an explicit id: the app generates one otherwise
 *         submit: { wait: true }, // and the round trip is not switched on for you
 *         fields: [{ id: 'reason', type: 'textarea', required: true }],
 *       } }],
 *     }],
 *   })
 * } finally {
 *   off()
 * }
 * ```
 *
 * The handler stays until you call the returned function; a later registration
 * for the same `id` replaces it. Outside the app nothing is registered.
 */
export function onSurfaceAction(id: string, handler: SurfaceActionHandler): () => void {
  if (typeof window === 'undefined' || !window.BMSNative) return () => {}
  return register(id, handler, isDevelopment())
}

/**
 * Closes the open surface of this web app; the pending `showForm`/`showContent`
 * resolves with `cancelled`. `{ ok: true }` even if none is open. Without `id`
 * whatever is open is closed. Requires `nativeForms` or `nativeContent`.
 */
export function closeSurface(payload: { id?: string } = {}): Promise<NativeResult> {
  return call('closeSurface', payload)
}

/**
 * The page's answer to `onNativeSurfaceAction`, within 60 seconds. You rarely
 * need it: the `onSubmit`/`onAction` options of `showForm`/`showContent` call it
 * for you. Requires `nativeForms` or `nativeContent`.
 */
export function surfaceResult(payload: SurfaceResultPayload): Promise<NativeResult> {
  return call('surfaceResult', payload)
}

// --- Fallback helpers --------------------------------------------------------

/**
 * Can this page open native forms? `false` outside the app, in an app build
 * that predates the feature and where the web app lacks `nativeForms`. Keep
 * your web form for those cases.
 */
export function canShowNativeForms(): boolean {
  return can('nativeForms')
}

/** Can this page open native content? Same rules as `canShowNativeForms`, for `nativeContent`. */
export function canShowNativeContent(): boolean {
  return can('nativeContent')
}

/**
 * Did the result come back because the native surface is not available here, so
 * the page should show its own web UI? That is `unavailable` (outside the app or
 * nothing to present on), `unknownAction` (the app is too old to know the call)
 * and `capability` (the web app is not allowed to). Not `cancelled`, `busy`,
 * `invalid`, `tooLarge` or `failed`: those are answers, not a missing feature.
 */
export function isNativeSurfaceUnsupported(result: NativeSurfaceResult): boolean {
  return (
    !result.ok &&
    (result.error === 'unavailable' ||
      result.error === 'unknownAction' ||
      result.error === 'capability')
  )
}
