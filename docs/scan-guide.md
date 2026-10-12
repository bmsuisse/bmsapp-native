# Scanning: text and several barcodes

This guide is for teams whose web app should read something with the iPhone
camera: a **serial number or article number printed on a label** (`scanText`), or
**several barcodes in one go**, for goods receipt or stock taking
(`scanBarcodes`). Both use the app's native scanner; the result goes straight to
the page. There is nothing to do in the backend.

Package: [`@bmsuisse/app-native`](../packages/app-native), file
[`scan.ts`](../packages/app-native/src/scan.ts).
For documents (`scanDocument`) see the [README](../packages/app-native/README.md).

```ts
import { scanText, scanBarcodes, scanBarcode, canScan } from '@bmsuisse/app-native'
```

## What the user sees

- **Text:** the camera image shows the lines of text the phone has recognized,
  highlighted. The user taps one and it goes back to the page. With a `pattern`
  only lines that match are highlighted and can be tapped.
- **Several barcodes:** the scanner stays open. Every new, distinct code is added
  to a list at the bottom (with a count, a short vibration for each code, swipe to
  remove one). **Done** hands over all codes in scan order, **Cancel** hands over
  nothing.

Real iPhones only: there is no camera scanner in the simulator or on very old
devices.

## Capability

`camera`, like `scanDocument`. Without it the app answers `capability`.
`canScan()` checks `BMSNative.capabilities`, but there is no way to know
beforehand that the device has a scanner: handle `unavailable`.

## `scanText(options?)`

| Option    | Type               | Meaning                                                          |
| --------- | ------------------ | ---------------------------------------------------------------- |
| `pattern` | `string \| RegExp` | Limits what can be picked. At most 200 characters. Empty = none. |

Result: `{ ok: true, text }` or a failure. `text` is the tapped line without
leading and trailing white space and line breaks.

```ts
// pick a serial number such as "AB-12345" from a label
const sn = await scanText({ pattern: '[A-Z]{2}-\\d{4,}' })
if (sn.ok) form.serial = sn.text
```

### The pattern

- It is an **ICU regular expression**, not a JavaScript one. Simple patterns are
  the same, but `\d` matches digits of every script, and lookbehind, named groups
  and some escapes differ in details. The package does not translate anything.
- It is matched **case-insensitively against the whole line**: `\d{4}` accepts
  `1234` but not `12345` or `No. 1234`.
- A `RegExp` is sent as its `source`; the `i` flag is dropped (matching is always
  case-insensitive). In development builds the package warns about other flags,
  about a pattern over 200 characters and about lookbehind / named groups.
- A pattern that is too long or does not compile is answered `invalid` right
  away; the scanner does not open.

Cookbook:

| You want                           | Pattern            |
| ---------------------------------- | ------------------ |
| Serial number `AB-1234`            | `[A-Z]{2}-\\d{4,}` |
| Article number with a fixed prefix | `ART-\\d{6}`       |
| A line that _contains_ a number    | `.*AB-\\d{4}.*`    |
| Any line (no filter)               | omit `pattern`     |

Text recognition works line by line. A label `S/N: AB-1234` therefore needs
`.*AB-\\d{4}.*`, or the page cleans the text itself after the scan.

## `scanBarcodes(options?)` and `scanBarcode(options)`

| Option    | For            | Meaning                                                                                   |
| --------- | -------------- | ----------------------------------------------------------------------------------------- |
| `formats` | both           | Limits the kinds (`BARCODE_FORMATS`). Unknown names are ignored; none usable = all kinds. |
| `max`     | `scanBarcodes` | Whole number 1 to 200. The scanner closes by itself at that many. Without: 200.           |

Formats: `aztec`, `codabar`, `code39`, `code93`, `code128`, `dataMatrix`, `ean8`,
`ean13`, `i2of5`, `itf14`, `pdf417`, `qr`, `upce` (the same names as the `barcode`
form field).

```ts
// collect up to 20 EAN-13 or QR codes (goods receipt)
const res = await scanBarcodes({ formats: ['ean13', 'qr'], max: 20 })
if (res.ok) addLines(res.values)
else if (res.error === 'cancelled') {
  /* user closed the scanner */
} else showHint(res.message)
```

Results:

| Call                         | Result                                        |
| ---------------------------- | --------------------------------------------- |
| `scanBarcodes(options)`      | `{ ok: true, values: string[] }` or a failure |
| `scanBarcode({ formats })`   | `{ ok: true, value: string }` or a failure    |
| `scanBarcode()` (no options) | `{ ok: true }` right away, as before          |

`values` are in scan order, every distinct code once (exact comparison), at least
one entry, at most `max`; codes the user removed are not in it.

## Errors

| `error`       | Meaning                                                               | `message`                           |
| ------------- | --------------------------------------------------------------------- | ----------------------------------- |
| `invalid`     | Options of the wrong type or out of range                             | English, for the developer          |
| `capability`  | The web app has no `camera` capability                                | English, for the developer          |
| `unavailable` | No scanner on this device, it cannot be shown now, or outside the app | for the user (from the app)         |
| `denied`      | Camera access is turned off for the app                               | for the user, in the app's language |
| `cancelled`   | The user closed the scanner. No callback is called.                   | –                                   |
| `busy`        | Another scan is already open                                          | –                                   |

Outside the app (no `window.BMSNative`) every call resolves
`{ ok: false, error: 'unavailable' }` and never throws. **Always keep a way to type
the value in.**

## Callbacks

The app also calls `window.onTextScanned(text)`, `window.onBarcodeScanned(value)`
(single scan) and `window.onBarcodesScanned(values)` (multi scan) if the page
defined them. With the package use `on('textScanned' | 'barcodeScanned' |
'barcodesScanned', …)`. **Both the promise and the callback fire — handle each
result once.** The promise is the way to use; the package never requires globals
and keeps one the page defined.

## App versions without the feature

- `scanText`: the app answers `unknownAction`; the package reports it as
  `unavailable`, so one fallback covers it.
- `scanBarcodes` / `scanBarcode({ formats })`: the old app **ignores the options**,
  runs the old single scan and answers `{ ok: true }` with no `value` / `values`;
  the code arrives only through `onBarcodeScanned`. The package recognizes that
  answer, waits for the callback and resolves **one** code, marked `oldApp: true`
  (`values: [code]` for `scanBarcodes`). `formats` and `max` were not applied.
  An old app reports no cancel, so that promise stays pending if the user closes
  the scanner.

Do not publish a web app version that depends on multi-scan before the app
version that has it is in use. Check `oldApp` if the count matters.

## Tips

Text recognition depends on light, distance and print size: small or curved print
is hard. Hold steady, and give the user the manual input as a fallback.
