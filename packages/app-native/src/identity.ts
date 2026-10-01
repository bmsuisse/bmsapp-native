// Sign-in with the Entra token of the app. The backend side is
// `bmsdna.app_native.entra`. Details: docs/entra-token-guide.md

import { call, type NativeResult } from './bridge.js'

export type AccessToken = {
  /** The Entra ID token (a JWT). Send it as `Authorization: Bearer <token>`. */
  token: string
  /** Expiry in seconds since 1970 (not milliseconds). */
  expiresAt: number
}

/**
 * The Entra ID token of the user's sign-in in the app. Requires `identity`.
 *
 * You do not need this for `fetch`/XHR to your own backend: the app attaches
 * the token to those automatically. Use it where the browser cannot set a
 * header, for example a `WebSocket` (send the token in the first message, not
 * in the URL), `EventSource` or your own HTTP client. A web worker cannot call
 * the bridge: ask here on the main thread, hand the token over and set the header
 * in the worker.
 *
 * After a 401 the app repeats a `fetch` once with a renewed token, but not an
 * `XMLHttpRequest` (HTTP libraries such as axios use it): the next call gets the new
 * token, so repeat it yourself.
 *
 * The token lives about one hour. Ask again shortly before `expiresAt`, or
 * pass `refresh: true` after your backend answered 401 to force a new one.
 * Never store it and never send it to a host other than your own backend.
 *
 * Errors: `capability` (`identity` not granted), `forbidden` (the page, or the
 * frame, does not belong to this web app), `notSignedIn` (nobody is signed in, or no
 * token can be had right now, for example offline with an expired one). Outside the
 * app: `unavailable`.
 */
export function getAccessToken(
  options: { refresh?: boolean } = {}
): Promise<NativeResult<AccessToken>> {
  return call<AccessToken>('getAccessToken', options.refresh ? { refresh: true } : {})
}
