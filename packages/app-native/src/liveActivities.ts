// Live Activities on the lock screen. Mirrored by hand from
// `bmsdna.app_native.live_activities` (LiveActivityState).
// Details: docs/live-activities-guide.md

import { call, type NativeResult } from './bridge.js'

export type LiveActivityState = {
  /** Main line. */
  title: string
  subtitle?: string
  /** Short status for the compact Dynamic Island. */
  status?: string
  /** 0…1. */
  progress?: number
  /** At most 5 named steps. */
  steps?: string[]
  /** Index into `steps`, 0-based. */
  currentStep?: number
  /** Countdown until then: ISO 8601 or Unix seconds. */
  timerEnd?: string | number
  icon?: string
  tint?: string
}

export type LiveActivityStart = {
  /** Your id, e.g. the order number. If it already exists, the activity is updated. */
  id: string
  state: LiveActivityState
  icon?: string
  tint?: string
  /** A tap opens the web app at this path. */
  path?: string
  /** ISO 8601: from then on the state is considered stale. */
  staleAt?: string
}

/** Requires `liveActivities`. Other errors: `disabled`, `invalid`, `failed`. */
export function startLiveActivity(activity: LiveActivityStart): Promise<NativeResult> {
  return call('startLiveActivity', activity)
}

/** New state; with `alert` also highlighted (sound, Dynamic Island expands). */
export function updateLiveActivity(update: {
  id: string
  state: LiveActivityState
  alert?: { title: string; body?: string }
}): Promise<NativeResult> {
  return call('updateLiveActivity', update)
}

/** Ends it. `dismiss`: `'immediate'`, an ISO timestamp, or omit it (iOS default). */
export function endLiveActivity(end: {
  id: string
  state?: LiveActivityState
  dismiss?: 'immediate' | (string & {})
}): Promise<NativeResult> {
  return call('endLiveActivity', end)
}

/** Ids of this web app's running activities. */
export function getLiveActivities(): Promise<NativeResult<{ ids: string[] }>> {
  return call('getLiveActivities')
}
