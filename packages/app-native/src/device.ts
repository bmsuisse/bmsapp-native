import { send, type NativeResult } from './bridge.js'

/**
 * Opens the native document scanner. The app itself uploads the result to
 * this web app's `documentUploadPath` (backend: `create_document_router` in
 * `bmsdna-app-native`). Requires `camera`.
 */
export function scanDocument(): Promise<NativeResult> {
  return send('scanDocument')
}

/**
 * Opens the native barcode/QR scanner. The scanned value arrives via
 * `on('barcodeScanned', value => …)`. Requires `camera`.
 */
export function scanBarcode(): Promise<NativeResult> {
  return send('scanBarcode')
}
