# @bmsuisse/app-native

Web app side of the BMS app: typed calls to `window.BMSNative`, which the
app injects into every web app — with browser fallbacks, so the same page
also runs outside the app. No dependencies, no React required.

Backend counterpart: [`bmsdna-app-native`](../../python/app-native)
(Python). Detailed guides per topic: [`docs/`](../../docs), for native forms and
content [native-surfaces-guide.md](../../docs/native-surfaces-guide.md).

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
  scanBarcodes,
  scanText,
  setWidgets,
  getAccessToken,
  navigate,
  addReminder,
  saveContact,
  callPhone,
  toIsoWithOffset,
  canShowNativeForms,
  isNativeSurfaceUnsupported,
  showForm,
  showContent,
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

// Or let the promise carry the result: several codes, or text from a label
// (docs/scan-guide.md). Keep a way to type the value in.
const codes = await scanBarcodes({ formats: ['ean13', 'qr'], max: 20 })
const serial = await scanText({ pattern: '[A-Z]{2}-\d{4,}' })

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

// Native form (an iOS sheet). The form stays open until your handler settles:
// `{ fieldErrors }` or a thrown error marks fields and lets the user correct.
if (canShowNativeForms()) {
  const res = await showForm(
    {
      id: 'new-customer',
      title: 'New customer',
      fields: [
        { id: 'name', type: 'text', label: 'Company name', required: true },
        { id: 'email', type: 'email', label: 'Email', required: true },
        { id: 'card', type: 'photo', label: 'Business card', max: 1 },
      ],
    },
    { onSubmit: async (values) => await api.createCustomer(values) }
  )
  if (!res.ok && isNativeSurfaceUnsupported(res)) openWebForm() // old app, no capability
} else {
  openWebForm()
}

// Native content: info with blocks and buttons
const shown = await showContent({
  title: 'Miller Ltd',
  blocks: [
    { type: 'facts', items: [{ label: 'Phone', value: '+41 44 000 00 00', kind: 'phone' }] },
  ],
  actions: [{ id: 'new-order', label: 'New order', style: 'primary' }],
})
```

## Behavior outside the app

| Function                                                          | Browser                                                                           |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `toast`, `haptic`, `setBadge`, `setChrome`                        | does nothing                                                                      |
| `share`                                                           | Web Share API, otherwise clipboard (`'copied'`)                                   |
| `openExternal`                                                    | new tab                                                                           |
| `biometricConfirm`                                                | `{ ok: true }` (web flow continues)                                               |
| `navigate`                                                        | route in Google Maps in a new tab                                                 |
| `callPhone`                                                       | `tel:` link                                                                       |
| `showForm`, `showContent`, `closeSurface`                         | `{ ok: false, error: 'unavailable' }` — keep your web UI (`canShowNativeForms()`) |
| all others (`setWidgets`, `startLiveActivity`, `scanDocument`, …) | `{ ok: false, error: 'unavailable' }`                                             |

## Responses and errors

Calls with a response return `{ ok: true, … }` or `{ ok: false, error }`.
Common errors: `capability` (the app has not granted the capability to the
web app), `invalid`, `cancelled`, `unavailable`, `notConfigured`; for
`getAccessToken` also `forbidden` and `notSignedIn`; for the device actions also
`denied`; for `showForm`/`showContent` also `forbidden`, `busy` and `tooLarge`.
An app that predates a call answers `unknownAction`: treat it like `unavailable`.
`can(capability)` saves unnecessary calls, but the app always checks on its
own.

## Overview

| Area            | Functions                                                                                                              | Capability                                                             |
| --------------- | ---------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Detection       | `isNativeApp`, `nativeInfo`, `can`                                                                                     | –                                                                      |
| Events          | `on('menuSelect' \| 'actionButtonTap' \| 'bottomBarTap' \| 'barcodeScanned' \| 'barcodesScanned' \| 'textScanned', …)` | –                                                                      |
| Chrome          | `setChrome`, `centerProminentEntry`                                                                                    | `customChrome`, `customBottomBar`                                      |
| Feedback        | `toast`, `haptic`, `setBadge`                                                                                          | –                                                                      |
| System          | `share`, `openExternal`, `biometricConfirm`                                                                            | –                                                                      |
| Camera          | `scanDocument`, `scanBarcode`, `scanBarcodes`, `scanText`, `canScan` ([guide](../../docs/scan-guide.md))               | `camera`                                                               |
| Widgets         | `setWidgets`, `updateWidget`, `removeWidgets`, `refreshWidgets`                                                        | `dashboardWidgets`                                                     |
| Live Activities | `startLiveActivity`, `updateLiveActivity`, `endLiveActivity`, `getLiveActivities`                                      | `liveActivities`                                                       |
| Approvals       | `refreshApprovals`                                                                                                     | `approvals`                                                            |
| Sign-in         | `getAccessToken`                                                                                                       | `identity`                                                             |
| Other apps      | `navigate`, `callPhone`, `addReminder`, `saveContact`, `toIsoWithOffset`                                               | `deviceApps` (reminder, contact)                                       |
| Native forms    | `showForm`, `canShowNativeForms`, `formLimitWarnings`                                                                  | `nativeForms` (+ `camera` for camera fields)                           |
| Native content  | `showContent`, `canShowNativeContent`, `contentLimitWarnings`                                                          | `nativeContent` (+ `deviceApps` for `saveContact`/`addReminder` steps) |
| Surfaces        | `closeSurface`, `surfaceResult`, `isNativeSurfaceUnsupported`, `on('surfaceAction', …)`, `onSurfaceAction`             | `nativeForms` or `nativeContent`                                       |
| Testing         | `sendTestNotification`                                                                                                 | `notifications`                                                        |
| Raw access      | `call`, `post`, `send`                                                                                                 | –                                                                      |

## License

[MIT](LICENSE)
