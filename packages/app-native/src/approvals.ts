import { call, type NativeResult } from './bridge.js'

export type ApprovalDetail = { label: string; value: string }

/** A pending approval in the feed (`GET approvalsPath`); the same format as the Python `Approval` model. */
export type Approval = {
  /** Stable across fetches, comes back as `approval_id` with the decision. */
  id: string
  title: string
  subtitle?: string
  category?: string
  amount?: string
  requester?: string
  /** ISO 8601. */
  createdAt?: string
  /** ISO 8601. */
  dueAt?: string
  urgent?: boolean
  icon?: string
  /** At most 12 are shown. */
  details?: ApprovalDetail[]
  path?: string
  /**
   * BrAIn only: the chat this approval arose in. In a chat event the app fills it from the
   * stream; in the feed the server must send it. The app attaches the approval to that chat
   * and opens the chat from the inbox.
   */
  conversationId?: string
  approveLabel?: string
  rejectLabel?: string
  approveComment?: 'none' | 'optional' | 'required'
  rejectComment?: 'none' | 'optional' | 'required'
  biometric?: boolean
}

/**
 * Reloads this web app's pending approvals (`approvalsPath`) right away,
 * e.g. after the page itself has approved something. Requires `approvals`.
 */
export function refreshApprovals(): Promise<NativeResult> {
  return call('refreshApprovals')
}
