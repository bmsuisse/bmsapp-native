# @bmsuisse/app-native

Web app side of the BMS app: typed calls to `window.BMSNative`, which the
app injects into every web app — with browser fallbacks, so the same page
also runs outside the app. No dependencies, no React required.

Backend counterpart: [`bmsdna-app-native`](../../python/app-native)
(Python). Detailed guides per topic: [`docs/`](../../docs).

## Installation

```bash
npm install @bmsuisse/app-native
# or
bun add @bmsuisse/app-native
```

## Examples

```ts
import {
  isNativeApp,
  can,
  on,
  setChrome,
  toast,
  haptic,
  share,
  biometricConfirm,
  scanBarcode,
  setWidgets,
  getAccessToken,
  navigate,
  addReminder,
  saveContact,
  callPhone,
  toIsoWithOffset,
} from '@bmsuisse/app-native'

// Is the page running in the app? Does it have a given capability?
if (isNativeApp() && can('customChrome')) {
  setChrome({
    scope: 'route',
    menu: [{ items: [{ id: 'new-order', label: 'New order', icon: 'plus' }] }],
    actionButtons: [{ id: 'search', icon: 'magnifyingglass' }],
  })
}

// Taps in the native menu — instead of setting window.onNativeMenuSelect yourself
const off = on('menuSelect', (id) => navigate(`/${id}`))

// Feedback
toast('Saved', 'success')
haptic('success')

// Share: app → native share sheet, browser → Web Share API / clipboard
await share({ title: 'Order 123', url: location.href })

// Face ID before a critical action (UX only, no proof for the backend)
const { ok } = await biometricConfirm('Approve order?')

// Scan a barcode; the result arrives as an event
on('barcodeScanned', (value) => lookup(value))
await scanBarcode()

// Widgets on the native dashboard
await setWidgets([{ id: 'open-orders', kind: 'kpi', title: 'Open', data: { value: 12 } }])

// Entra token of the app's sign-in. Only needed where the browser cannot set a
// header (WebSocket, EventSource, …): fetch/XHR to your own backend get it automatically.
const session = await getAccessToken()
if (session.ok) socket.send(JSON.stringify({ token: session.token }))

// Other apps on the iPhone: route, reminder, contact, phone call
await navigate({ destination: { name: 'Müller AG', address: 'Industriestrasse 5, 4600 Olten' } })
await addReminder({ title: 'Call Mr. Meier back', due: toIsoWithOffset(new Date(2026, 9, 2, 9)) })
await saveContact({ givenName: 'Anna', organization: 'Müller AG', phones: ['+41 44 000 00 00'] })
await callPhone({ number: '+41 44 000 00 00' })
```

## Behavior outside the app

| Function                                                          | Browser                                         |
| ----------------------------------------------------------------- | ----------------------------------------------- |
| `toast`, `haptic`, `setBadge`, `setChrome`                        | does nothing                                    |
| `share`                                                           | Web Share API, otherwise clipboard (`'copied'`) |
| `openExternal`                                                    | new tab                                         |
| `biometricConfirm`                                                | `{ ok: true }` (web flow continues)             |
| `navigate`                                                        | route in Google Maps in a new tab               |
| `callPhone`                                                       | `tel:` link                                     |
| all others (`setWidgets`, `startLiveActivity`, `scanDocument`, …) | `{ ok: false, error: 'unavailable' }`           |

## Responses and errors

Calls with a response return `{ ok: true, … }` or `{ ok: false, error }`.
Common errors: `capability` (the app has not granted the capability to the
web app), `invalid`, `cancelled`, `unavailable`, `notConfigured`; for
`getAccessToken` also `forbidden` and `notSignedIn`; for the device actions also
`denied`.
`can(capability)` saves unnecessary calls, but the app always checks on its
own.

## Overview

| Area            | Functions                                                                         | Capability                        |
| --------------- | --------------------------------------------------------------------------------- | --------------------------------- |
| Detection       | `isNativeApp`, `nativeInfo`, `can`                                                | –                                 |
| Events          | `on('menuSelect' \| 'actionButtonTap' \| 'bottomBarTap' \| 'barcodeScanned', …)`  | –                                 |
| Chrome          | `setChrome`, `centerProminentEntry`                                               | `customChrome`, `customBottomBar` |
| Feedback        | `toast`, `haptic`, `setBadge`                                                     | –                                 |
| System          | `share`, `openExternal`, `biometricConfirm`                                       | –                                 |
| Camera          | `scanDocument`, `scanBarcode`                                                     | `camera`                          |
| Widgets         | `setWidgets`, `updateWidget`, `removeWidgets`, `refreshWidgets`                   | `dashboardWidgets`                |
| Live Activities | `startLiveActivity`, `updateLiveActivity`, `endLiveActivity`, `getLiveActivities` | `liveActivities`                  |
| Approvals       | `refreshApprovals`                                                                | `approvals`                       |
| Sign-in         | `getAccessToken`                                                                  | `identity`                        |
| Other apps      | `navigate`, `callPhone`, `addReminder`, `saveContact`, `toIsoWithOffset`          | `deviceApps` (reminder, contact)  |
| Testing         | `sendTestNotification`                                                            | `notifications`                   |
| Raw access      | `call`, `post`, `send`                                                            | –                                 |

## License

[MIT](LICENSE)
