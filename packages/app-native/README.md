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
  hasFeature,
  scanDocument,
  pickFiles,
  onDocumentsReceived,
  previewFile,
  dictate,
  getLayout,
  keyboardHeight,
  onBackRequested,
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

// What the app can do: window.BMSNative.features (older apps have none)
if (hasFeature('scanOptions')) {
  // Scan several supplier offers; each is one PDF, uploaded to your backend
  const scanned = await scanDocument({ kind: 'supplier-offer', multiple: true })
  if (scanned.ok) attach(scanned.documents) // NativeDocument[]
}

// Pick a PDF, a mail or a photo (in the browser: a file input)
const picked = await pickFiles({
  sources: ['files', 'photos'],
  accept: ['application/pdf', '.eml'],
})

// Files shared from other apps into this web app: set up once, early
const stopReceiving = onDocumentsReceived(({ documents }) => importOffers(documents))

// Preview a file of your own origin natively; dictate; keep an input above the keyboard
await previewFile({ url: '/api/offers/4711/file', filename: 'Offer 4711.pdf' })
const spoken = await dictate({ locale: 'de-CH' })
on('layoutChange', () => chat.scrollToBottom())

// Take over the back button while a dialog is open
const stopBack = onBackRequested((source) => (dialogOpen ? (closeDialog(), true) : false))

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

| Function                                                                                                              | Browser                                                                                                     |
| --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `toast`, `haptic`, `setBadge`, `setChrome`                                                                            | does nothing                                                                                                |
| `share`                                                                                                               | Web Share API, otherwise clipboard (`'copied'`)                                                             |
| `openExternal`                                                                                                        | new tab                                                                                                     |
| `biometricConfirm`                                                                                                    | `{ ok: true }` (web flow continues)                                                                         |
| `navigate`                                                                                                            | route in Google Maps in a new tab                                                                           |
| `pickFiles`                                                                                                           | hidden `<input type="file">` (`accept`, `multiple`, `capture`), mode `return` only; `upload` is unavailable |
| `previewFile`                                                                                                         | opens the URL in a new tab                                                                                  |
| `onBackRequested`                                                                                                     | does nothing (no-op cleanup)                                                                                |
| `onDocumentsReceived`                                                                                                 | registers the handler, which is never called                                                                |
| `keyboardHeight`                                                                                                      | height from `visualViewport`                                                                                |
| `callPhone`                                                                                                           | `tel:` link                                                                                                 |
| `showForm`, `showContent`, `closeSurface`                                                                             | `{ ok: false, error: 'unavailable' }` — keep your web UI (`canShowNativeForms()`)                           |
| all others (`setWidgets`, `startLiveActivity`, `scanDocument`, `dictate`, `getLayout`, `consumeReceivedDocuments`, …) | `{ ok: false, error: 'unavailable' }`                                                                       |

## Responses and errors

Calls with a response return `{ ok: true, … }` or `{ ok: false, error }`.
Common errors: `capability` (the app has not granted the capability to the
web app), `invalid`, `cancelled`, `unavailable`, `notConfigured`; for
`getAccessToken` also `forbidden` and `notSignedIn`; for the device actions also
`denied`; for `showForm`/`showContent` also `forbidden`, `busy` and `tooLarge`; for
`getAccessToken({ resource })` also `consentRequired`; for documents `tooLarge` (per
document, beyond 25,000,000 bytes).
An app that predates a call answers `unknownAction`: treat it like `unavailable`. The
calls of the 2026-11 contract (`pickFiles`, `dictate`, `getLayout`, `previewFile`,
`onBackRequested`, `onDocumentsReceived`, `getAccessToken({ resource })` and
`scanDocument` with options) look at `hasFeature(…)` first: an app that does not list the
feature (older apps have no list) is not asked and the answer is `unavailable`. An invalid
payload (a `context` over 4096 bytes, a bad `kind`, empty `sources`, a `maxSeconds` out of
range, a foreign-origin `url`, …) answers `invalid` without calling the app; development
builds also warn. Nothing throws.
`can(capability)` saves unnecessary calls, but the app always checks on its
own.

## Overview

| Area            | Functions                                                                                                                                | Capability                                                             |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Detection       | `isNativeApp`, `nativeInfo`, `can`                                                                                                       | –                                                                      |
| Detection       | `hasFeature`, `FEATURES` (what the app implements, see [chrome guide](../../docs/webapp-chrome-guide.md))                                | –                                                                      |
| Events          | `on('menuSelect' \| 'actionButtonTap' \| 'bottomBarTap' \| 'barcodeScanned' \| 'barcodesScanned' \| 'textScanned' \| 'layoutChange', …)` | –                                                                      |
| Chrome          | `setChrome`, `centerProminentEntry`                                                                                                      | `customChrome`, `customBottomBar`                                      |
| Feedback        | `toast`, `haptic`, `setBadge`                                                                                                            | –                                                                      |
| System          | `share`, `openExternal`, `biometricConfirm`                                                                                              | –                                                                      |
| Camera          | `scanDocument`, `scanBarcode`, `scanBarcodes`, `scanText`, `canScan` ([guide](../../docs/scan-guide.md))                                 | `camera`                                                               |
| Documents       | `pickFiles`, `onDocumentsReceived`, `consumeReceivedDocuments`, `previewFile` ([guide](../../docs/documents-guide.md))                   | `camera` (source camera), `receiveDocuments`                           |
| Voice           | `dictate` ([guide](../../docs/voice-guide.md))                                                                                           | `microphone`                                                           |
| Layout, back    | `getLayout`, `keyboardHeight`, `on('layoutChange', …)`, `onBackRequested` ([guide](../../docs/webapp-chrome-guide.md))                   | –                                                                      |
| Widgets         | `setWidgets`, `updateWidget`, `removeWidgets`, `refreshWidgets`                                                                          | `dashboardWidgets`                                                     |
| Live Activities | `startLiveActivity`, `updateLiveActivity`, `endLiveActivity`, `getLiveActivities`                                                        | `liveActivities`                                                       |
| Approvals       | `refreshApprovals`                                                                                                                       | `approvals`                                                            |
| Sign-in         | `getAccessToken` (also `{ resource, interactive }` for another API, [guide](../../docs/entra-token-guide.md))                            | `identity`                                                             |
| Other apps      | `navigate`, `callPhone`, `addReminder`, `saveContact`, `toIsoWithOffset`                                                                 | `deviceApps` (reminder, contact)                                       |
| Native forms    | `showForm`, `canShowNativeForms`, `formLimitWarnings`                                                                                    | `nativeForms` (+ `camera` for camera fields)                           |
| Native content  | `showContent`, `canShowNativeContent`, `contentLimitWarnings`                                                                            | `nativeContent` (+ `deviceApps` for `saveContact`/`addReminder` steps) |
| Surfaces        | `closeSurface`, `surfaceResult`, `isNativeSurfaceUnsupported`, `on('surfaceAction', …)`, `onSurfaceAction`                               | `nativeForms` or `nativeContent`                                       |
| Testing         | `sendTestNotification`                                                                                                                   | `notifications`                                                        |
| Raw access      | `call`, `post`, `send`                                                                                                                   | –                                                                      |

## License

[MIT](LICENSE)
