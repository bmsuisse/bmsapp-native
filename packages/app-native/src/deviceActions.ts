// Actions in other apps on the iPhone: route in a navigation app, reminder,
// contact, phone call. Calendar events are deliberately not included.
// Details: docs/device-actions-guide.md

import { call } from './bridge.js'
import { openExternal } from './ui.js'

/** Error codes of the device actions. */
export type DeviceActionError =
  | 'invalid'
  | 'unknownAction'
  | 'capability'
  | 'denied'
  | 'cancelled'
  | 'unavailable'
  | 'failed'

/**
 * Response of every device action.
 *
 * `message` is a finished sentence for the user. From the app it is German.
 * Where the app sends none (for example `capability`) or the page runs
 * outside the app, the package fills in a short English one — so `message`
 * is always a string, but do not rely on its wording: show your own texts
 * based on `error`.
 *
 * Further fields are additional information, for example `app: 'google'` or
 * `waypoints_ignored: 'true'` for `navigate`, `list: 'Reminders'` for
 * `addReminder`. They are always strings.
 */
export type DeviceActionResult = {
  ok: boolean
  message: string
  error?: DeviceActionError
  [extra: string]: unknown
}

// --- navigate ---------------------------------------------------------------

/**
 * A place by address, by coordinates, or both (coordinates win). It needs one of
 * the two: a `name` alone is only a label and is not enough.
 */
export type Place = { address?: string; name?: string; latitude?: number; longitude?: number }

export type TravelMode = 'driving' | 'walking' | 'transit' | 'cycling'

export type NavigationApp = 'apple' | 'google' | 'waze'

type NavigateOptions = {
  /** Intermediate stops. Only Google Maps can take them; the others ignore them. */
  waypoints?: Array<Place | string>
  /** Default `driving`. */
  mode?: TravelMode
  /** Without it the user's choice applies (the app asks the first time). */
  app?: NavigationApp
}

/**
 * The destination as `destination` (a place or an address as text) or flat:
 * `{ address }` or `{ latitude, longitude, name? }`.
 */
export type NavigatePayload = NavigateOptions &
  (
    | { destination: Place | string }
    | { address: string; name?: string }
    | { latitude: number; longitude: number; name?: string }
  )

// --- addReminder ------------------------------------------------------------

export type ReminderPriority = 'high' | 'medium' | 'low'

export type AddReminderPayload = {
  title: string
  /**
   * ISO 8601. A date alone (`'2026-10-02'`) is all day. Without a time zone
   * (`'2026-10-02T09:00'`) it is the time of the iPhone. With a time zone it is
   * taken exactly. See `toIsoWithOffset` and `toDateOnly` for a `Date`.
   */
  due?: string
  /** Treat `due` as all day although it has a time. */
  allDay?: boolean
  notes?: string
  priority?: ReminderPriority
  /** Name of the reminders list; without it the default list. */
  list?: string
  url?: string
  /**
   * `true` (default): the app asks first. `false`: it saves right away. Either way
   * the app needs the iOS access to Reminders.
   */
  confirm?: boolean
}

// --- saveContact ------------------------------------------------------------

export type PhoneLabel = 'mobile' | 'work' | 'home' | 'main' | 'other'
export type EmailLabel = 'work' | 'home' | 'other'

export type ContactPhone = string | { label?: PhoneLabel; value: string }
export type ContactEmail = string | { label?: EmailLabel; value: string }
export type ContactAddress = {
  street?: string
  postalCode?: string
  city?: string
  country?: string
}

type ContactDetails = {
  jobTitle?: string
  phones?: ContactPhone[]
  emails?: ContactEmail[]
  address?: ContactAddress
  url?: string
  /**
   * `true` (default): the app shows the system contact form first, where the
   * user can still change things. `false`: it saves right away. Either way the
   * app needs the iOS access to Contacts.
   */
  confirm?: boolean
}

/** At least one of `givenName`, `familyName` or `organization`. */
export type SaveContactPayload = ContactDetails &
  (
    | { givenName: string; familyName?: string; organization?: string }
    | { familyName: string; givenName?: string; organization?: string }
    | { organization: string; givenName?: string; familyName?: string }
  )

// --- callPhone --------------------------------------------------------------

export type CallPhonePayload = {
  /** Preferably international, e.g. `'+41 44 000 00 00'`. Spaces are removed. */
  number: string
}

// --- helpers ----------------------------------------------------------------

const MESSAGES: Record<string, string> = {
  invalid: 'The details are incomplete or invalid.',
  unknownAction: 'This version of the app cannot do that yet.',
  capability: 'This web app is not allowed to do that. The capability is missing in the app.',
  denied: 'Access is not allowed. It has to be allowed in the app settings of the iPhone.',
  cancelled: 'Cancelled.',
  unavailable: 'This only works inside the BMS app.',
  failed: 'The action failed.',
}

function result(
  ok: boolean,
  error: DeviceActionError | undefined,
  message?: string,
  extra: Record<string, unknown> = {}
): DeviceActionResult {
  return {
    ...extra,
    ok,
    ...(error && { error }),
    message: message || (ok ? 'Done.' : (MESSAGES[error ?? 'failed'] ?? 'The action failed.')),
  }
}

async function run(action: string, payload: Record<string, unknown>): Promise<DeviceActionResult> {
  const response = (await call(action, payload)) as Record<string, unknown>
  const { ok, error, message, ...extra } = response
  return result(
    ok === true,
    typeof error === 'string' ? (error as DeviceActionError) : undefined,
    typeof message === 'string' ? message : undefined,
    extra
  )
}

function inApp(): boolean {
  return typeof window !== 'undefined' && !!window.BMSNative
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

/** `lat,lon` for valid coordinates, otherwise the address or name. */
function placeQuery(place: Place | string | undefined): string | undefined {
  if (typeof place === 'string') return place.trim() || undefined
  if (!place) return undefined
  const { latitude, longitude } = place
  if (
    finite(latitude) &&
    finite(longitude) &&
    Math.abs(latitude) <= 90 &&
    Math.abs(longitude) <= 180
  ) {
    return `${latitude},${longitude}`
  }
  // A name alone is no place: the app answers `invalid` for it, and so does the fallback.
  return place.address?.trim() || undefined
}

const GOOGLE_MODE: Record<TravelMode, string> = {
  driving: 'driving',
  walking: 'walking',
  transit: 'transit',
  cycling: 'bicycling',
}

/** The web route in Google Maps for a browser, `undefined` without a destination. */
function webRouteUrl(payload: NavigatePayload): string | undefined {
  // Flat form: the payload itself carries `address` or `latitude`/`longitude`.
  const destination = placeQuery(
    'destination' in payload ? payload.destination : (payload as Place)
  )
  if (!destination) return undefined
  const params = new URLSearchParams({ api: '1', destination })
  const stops = (payload.waypoints ?? []).map(placeQuery).filter((s): s is string => !!s)
  if (stops.length) params.set('waypoints', stops.join('|'))
  if (payload.mode) params.set('travelmode', GOOGLE_MODE[payload.mode] ?? 'driving')
  return `https://www.google.com/maps/dir/?${params.toString()}`
}

/** Only `+` (first character) and digits, like the app — `tel:` does not like spaces. */
function phoneDigits(text: string): string {
  let digits = ''
  Array.from(text.trim()).forEach((character, index) => {
    if (/^[0-9]$/.test(character) || (character === '+' && index === 0)) digits += character
  })
  return digits
}

// --- actions ----------------------------------------------------------------

/**
 * Starts a route in a navigation app (Apple Maps, Google Maps or Waze,
 * depending on `app` or the user's choice). It always opens on the iPhone; if the
 * app is not in the foreground the user gets a notification to tap instead, and
 * the response is still `ok`. Needs no capability.
 *
 * Outside the app the route opens in Google Maps in a new tab.
 */
export function navigate(payload: NavigatePayload): Promise<DeviceActionResult> {
  if (inApp()) return run('navigate', payload)
  const url = webRouteUrl(payload)
  if (!url) return Promise.resolve(result(false, 'invalid', 'The route needs a destination.'))
  openExternal(url)
  return Promise.resolve(
    result(true, undefined, 'The route opened in Google Maps.', { app: 'google' })
  )
}

/**
 * Creates a reminder in Apple Reminders. Requires `deviceApps`. By default the
 * app asks the user first (`confirm: false` skips that; the iOS access to
 * Reminders is needed either way). A `due`, `url` or `priority` the app cannot
 * read is ignored without an error. Errors: `capability`, `denied`, `cancelled`,
 * `invalid`, `unavailable`, `failed`.
 *
 * Outside the app: `{ ok: false, error: 'unavailable' }`.
 */
export function addReminder(payload: AddReminderPayload): Promise<DeviceActionResult> {
  return run('addReminder', payload)
}

/**
 * Saves a contact. Requires `deviceApps`. By default the app shows the system
 * contact form first (`confirm: false` saves right away; the iOS access to
 * Contacts is needed either way). Errors as for `addReminder`.
 *
 * Outside the app: `{ ok: false, error: 'unavailable' }`.
 */
export function saveContact(payload: SaveContactPayload): Promise<DeviceActionResult> {
  return run('saveContact', payload)
}

/**
 * Starts a phone call; iOS asks before dialing. Needs no capability.
 *
 * Outside the app it opens a `tel:` link.
 */
export function callPhone(payload: CallPhonePayload): Promise<DeviceActionResult> {
  if (inApp()) return run('callPhone', payload)
  const number = phoneDigits(payload.number)
  if (!number) return Promise.resolve(result(false, 'invalid', 'The phone number is not valid.'))
  const link = document.createElement('a')
  link.href = `tel:${number}`
  document.body.appendChild(link) // Firefox only follows links that are in the document
  link.click()
  link.remove()
  return Promise.resolve(result(true, undefined, `Calling ${number}.`))
}

// --- dates ------------------------------------------------------------------

function pad(value: number, width = 2): string {
  return String(Math.trunc(Math.abs(value))).padStart(width, '0')
}

/**
 * ISO 8601 in the local time zone of the browser with its offset, e.g.
 * `'2026-10-02T09:00:00+02:00'` — the form the app takes exactly. Without the
 * offset the app would read the time in the time zone of the iPhone.
 * (`date.toISOString()` is UTC and also fine, but shows another wall-clock time.)
 */
export function toIsoWithOffset(date: Date): string {
  if (Number.isNaN(date.getTime())) throw new RangeError('Invalid date')
  const offset = -date.getTimezoneOffset() // minutes east of UTC
  const sign = offset < 0 ? '-' : '+'
  return (
    `${pad(date.getFullYear(), 4)}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
    `${sign}${pad(offset / 60)}:${pad(offset % 60)}`
  )
}

/**
 * The local calendar date as `'2026-10-02'` — for an all-day `due`. Do not use
 * `toISOString().slice(0, 10)`: that is the UTC date and is off by one
 * in the evening or the early morning.
 */
export function toDateOnly(date: Date): string {
  if (Number.isNaN(date.getTime())) throw new RangeError('Invalid date')
  return `${pad(date.getFullYear(), 4)}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
