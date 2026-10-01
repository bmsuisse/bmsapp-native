import { send, type NativeResult } from './bridge.js'

export type TestNotification = {
  title?: string
  body?: string
  /** Seconds until it is shown. */
  delay?: number
  /** Buttons in the app's notifications tab. */
  actions?: Array<{ id: string; title: string }>
  level?: 'time-sensitive' | 'critical'
  /** `critical` only: label of the acknowledge button. */
  ackLabel?: string
}

/**
 * Schedules a purely local notification that looks like a real push —
 * for testing without a backend. Requires `notifications`.
 */
export function sendTestNotification(notification: TestNotification = {}): Promise<NativeResult> {
  return send('sendTestNotification', notification)
}
