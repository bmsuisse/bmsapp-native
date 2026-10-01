import { call, type NativeResult } from './bridge.js'

/**
 * Reloads this web app's pending approvals (`approvalsPath`) right away,
 * e.g. after the page itself has approved something. Requires `approvals`.
 */
export function refreshApprovals(): Promise<NativeResult> {
  return call('refreshApprovals')
}
