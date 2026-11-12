// Sign-in with the Entra token of the app. The backend side is
// `bmsdna.app_native.entra`. Details: docs/entra-token-guide.md

import { call, type NativeFailure, type NativeResult } from './bridge.js'
import { asFailure, badAnswer, callFeature, invalid } from './internal.js'

export type AccessToken = {
  /** The Entra ID token (a JWT). Send it as `Authorization: Bearer <token>`. */
  token: string
  /** Expiry in seconds since 1970 (not milliseconds). */
  expiresAt: number
  /** Only with `getAccessToken({ resource })`: the resource the token is for. */
  resource?: string
}

export type AccessTokenOptions = {
  /** Force a new token (after your backend answered 401). */
  refresh?: boolean
  /**
   * A token for another API: an Entra scope such as `api://<app-id>/.default`.
   * Only works if that resource is configured for this web app in the app (else
   * `forbidden`). Needs the feature `tokenResources`; an older app would hand out
   * the normal token, so there `unavailable` is answered without asking it.
   */
  resource?: string
  /**
   * With `resource` only: let the app show the consent screen if the user has not
   * consented yet, instead of answering `consentRequired`.
   */
  interactive?: boolean
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
 * With `resource` you get a token for another API (an Entra scope such as
 * `api://<app-id>/.default`), silently acquired. Only the resources configured
 * for this web app in the app are allowed (`forbidden` otherwise). The answer
 * also carries `resource`. If the user still has to consent: `consentRequired`;
 * `interactive: true` lets the app show the consent screen instead. Cache tokens
 * per resource. Needs the feature `tokenResources` (else `unavailable`).
 *
 * Errors: `capability` (`identity` not granted), `forbidden` (the page, or the
 * frame, does not belong to this web app, or the resource is not configured for
 * it), `notSignedIn` (nobody is signed in, or no token can be had right now, for
 * example offline with an expired one), `consentRequired`, `invalid` (bad
 * options, the app is not asked). Outside the app: `unavailable`.
 */
export async function getAccessToken(
  options: AccessTokenOptions = {}
): Promise<NativeResult<AccessToken> | NativeFailure> {
  const payload: Record<string, unknown> = {}
  if (options.refresh) payload.refresh = true
  if (options.resource === undefined) return call<AccessToken>('getAccessToken', payload)

  if (typeof options.resource !== 'string' || options.resource === '') {
    return invalid(
      'getAccessToken',
      'resource has to be an Entra scope such as "api://<app-id>/.default".'
    )
  }
  if (options.interactive !== undefined && typeof options.interactive !== 'boolean') {
    return invalid('getAccessToken', 'interactive has to be a boolean.')
  }
  payload.resource = options.resource
  if (options.interactive) payload.interactive = true
  const answer = await callFeature<AccessToken>('tokenResources', 'getAccessToken', payload)
  if (!answer.ok) return asFailure(answer)
  const { token, expiresAt, resource } = answer as Partial<AccessToken>
  return typeof token === 'string' && typeof expiresAt === 'number'
    ? { ok: true, token, expiresAt, resource: resource ?? options.resource }
    : badAnswer()
}
