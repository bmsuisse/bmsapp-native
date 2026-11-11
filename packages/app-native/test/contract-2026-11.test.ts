// The fixtures of the 2026-11 contract (contract-fixtures/*.json, see the README
// there), run through the package: valid options reach the app unchanged, invalid
// ones answer `invalid` without calling it, and the app's answers come back as
// they are — or as `failed` if they are malformed.
//
// Typed objects first: the compiler checks one representative of each fixture
// against the exported types, the test checks that it is in the JSON file.

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  dictate,
  getAccessToken,
  getLayout,
  consumeReceivedDocuments,
  on,
  onBackRequested,
  onDocumentsReceived,
  pickFiles,
  previewFile,
  scanDocument,
  type BackSource,
  type Feature,
  type LayoutInfo,
  type NativeDocument,
  type PickFilesOptions,
  type ScanDocumentOptions,
} from '../src/index.js'
import scanResultJson from '../../../contract-fixtures/scan-result.json'
import pickFilesJson from '../../../contract-fixtures/pick-files.json'
import documentsReceivedJson from '../../../contract-fixtures/documents-received.json'
import dictateJson from '../../../contract-fixtures/dictate.json'
import layoutJson from '../../../contract-fixtures/layout.json'
import backRequestedJson from '../../../contract-fixtures/back-requested.json'
import previewFileJson from '../../../contract-fixtures/preview-file.json'
import accessTokenResourceJson from '../../../contract-fixtures/access-token-resource.json'
import { installBridge, removeBridge } from './helpers.js'

afterEach(removeBridge)

const ALL_FEATURES: Feature[] = [
  'scanResult',
  'scanOptions',
  'pickFiles',
  'receiveDocuments',
  'mediaCapture',
  'dictate',
  'layout',
  'backInterception',
  'previewFile',
  'tokenResources',
]

// --- Typed representatives ---------------------------------------------------------

const scanOptions: ScanDocumentOptions = {
  kind: 'supplier-offer',
  mode: 'return',
  multiple: true,
  context: { offerId: 'O-2026-0042' },
}
const pickOptions: PickFilesOptions = {
  sources: ['files', 'photos', 'camera'],
  accept: ['application/pdf', 'image/jpeg', '.eml', '.msg'],
  multiple: true,
  mode: 'return',
  kind: 'pick',
}
const uploaded: NativeDocument = {
  name: 'scan-2026-11-11.pdf',
  mime: 'application/pdf',
  size: 482113,
  pages: 3,
  uploadId: '8c2f1a4e-5b0a-4f3e-9d57-2b6f1c9e7a10',
  upload: { status: 200, body: { ok: true, id: 'doc-1' } },
}
const failed: NativeDocument = {
  name: 'scan-2.pdf',
  uploadId: '6f1e9c27-3a4b-4d58-b7a0-12c4e8d5f931',
  error: 'failed',
}
const tooLarge: NativeDocument = {
  name: 'catalog.pdf',
  mime: 'application/pdf',
  size: 30000000,
  uploadId: 'b2f6c9a1-4e87-4d35-a0b9-1c8e3f7d5a42',
  error: 'tooLarge',
}
const layout: LayoutInfo = {
  keyboardHeight: 336,
  keyboardVisible: true,
  sizeClass: 'regular',
  orientation: 'landscape',
  width: 1180,
  height: 320,
}

describe('typed representatives match the fixtures', () => {
  it('options and documents', () => {
    expect(scanResultJson.options.valid[2]?.value).toEqual(scanOptions)
    expect(pickFilesJson.options.valid[1]?.value).toEqual(pickOptions)
    expect(scanResultJson.results.valid[0]?.value).toEqual({ ok: true, documents: [uploaded] })
    expect(scanResultJson.results.valid[1]?.value.documents?.[1]).toEqual(failed)
    expect(pickFilesJson.results.valid[2]?.value.documents).toEqual([tooLarge])
  })

  it('layout', () => {
    expect(layoutJson.results.valid[1]?.value).toEqual({ ok: true, ...layout })
  })
})

// --- Running the fixtures ----------------------------------------------------------

type Case = { name: string; value: unknown; sent?: unknown; error?: string }
type Section = { valid?: Case[]; invalid?: Case[] }

/** `"@N"` in a `text` or `contextualStrings` value stands for N characters / N entries. */
function expand(value: unknown, key = ''): unknown {
  if (typeof value === 'string' && /^@\d+$/.test(value)) {
    const n = Number(value.slice(1))
    return key === 'contextualStrings' ? Array.from({ length: n }, () => 'a') : 'x'.repeat(n)
  }
  if (Array.isArray(value)) return value.map((v) => expand(v))
  if (typeof value === 'object' && value !== null) {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, expand(v, k)]))
  }
  return value
}

function withOrigin(value: unknown): unknown {
  return JSON.parse(JSON.stringify(value).replaceAll('{origin}', window.location.origin))
}

function answer(result: unknown) {
  return vi.fn(async (_action: string, _payload?: Record<string, unknown>) => result)
}

type Runner = (value: never) => Promise<unknown>

/** Valid options reach the app as they are, invalid ones never reach it. */
function runOptions(
  title: string,
  section: Section,
  action: string,
  run: Runner,
  mapSent: (v: unknown) => unknown = (v) => v
) {
  describe(`${title}: options`, () => {
    for (const c of section.valid ?? []) {
      it(`valid: ${c.name}`, async () => {
        const bridge = installBridge({
          features: ALL_FEATURES,
          call: answer({ ok: false, error: 'cancelled' }),
        })
        await run(mapSent(expand(c.value)) as never)
        expect(bridge.call).toHaveBeenCalledTimes(1)
        expect(bridge.call).toHaveBeenCalledWith(action, mapSent(expand(c.sent ?? c.value)))
      })
    }
    for (const c of section.invalid ?? []) {
      it(`invalid: ${c.name}`, async () => {
        vi.spyOn(console, 'warn').mockImplementation(() => {})
        const bridge = installBridge({ features: ALL_FEATURES })
        const res = await run(mapSent(expand(c.value)) as never)
        expect(res).toMatchObject({ ok: false, error: c.error })
        expect(bridge.call).not.toHaveBeenCalled()
      })
    }
  })
}

/** What the app answers comes back as it is; a malformed answer is `failed`. */
function runResults(title: string, section: Section, run: () => Promise<unknown>) {
  describe(`${title}: results`, () => {
    for (const c of section.valid ?? []) {
      it(`valid: ${c.name}`, async () => {
        installBridge({ features: ALL_FEATURES, call: answer(c.value) })
        expect(await run()).toEqual(c.value)
      })
    }
    for (const c of section.invalid ?? []) {
      it(`invalid: ${c.name}`, async () => {
        installBridge({ features: ALL_FEATURES, call: answer(c.value) })
        expect(await run()).toMatchObject({ ok: false, error: c.error })
      })
    }
  })
}

const origin = (v: unknown) => withOrigin(v)

runOptions('scan-result', scanResultJson.options as Section, 'scanDocument', (o) =>
  scanDocument(o as ScanDocumentOptions)
)
runResults('scan-result', scanResultJson.results as Section, () => scanDocument())

runOptions('pick-files', pickFilesJson.options as Section, 'pickFiles', (o) =>
  pickFiles(o as PickFilesOptions)
)
runResults('pick-files', pickFilesJson.results as Section, () => pickFiles({ sources: ['files'] }))

runOptions('dictate', dictateJson.options as Section, 'dictate', (o) => dictate(o))
runResults('dictate', dictateJson.results as Section, () => dictate())

runResults('layout', layoutJson.results as Section, () => getLayout())

runOptions(
  'preview-file',
  previewFileJson.options as Section,
  'previewFile',
  (o) => previewFile(o),
  origin
)
runResults('preview-file', previewFileJson.results as Section, () => previewFile({ url: '/a.pdf' }))

runOptions(
  'access-token-resource',
  accessTokenResourceJson.options as Section,
  'getAccessToken',
  (o) => getAccessToken(o)
)
runResults('access-token-resource', accessTokenResourceJson.results as Section, () =>
  getAccessToken({ resource: 'api://x/.default' })
)

describe('documents-received', () => {
  const flush = () => new Promise((resolve) => setTimeout(resolve))

  for (const c of (documentsReceivedJson.events as Section).valid ?? []) {
    it(`event, valid: ${c.name}`, async () => {
      installBridge({ features: ALL_FEATURES, call: answer({ ok: true, documents: [] }) })
      const handler = vi.fn()
      const off = onDocumentsReceived(handler)
      await flush()
      ;(
        window as unknown as { onNativeDocumentsReceived: (p: unknown) => void }
      ).onNativeDocumentsReceived(c.value)
      expect(handler).toHaveBeenCalledExactlyOnceWith(c.value)
      off()
    })
  }

  for (const c of (documentsReceivedJson.events as Section).invalid ?? []) {
    it(`event, ${c.error}: ${c.name}`, async () => {
      installBridge({ features: ALL_FEATURES, call: answer({ ok: true, documents: [] }) })
      const handler = vi.fn()
      const off = onDocumentsReceived(handler)
      await flush()
      ;(
        window as unknown as { onNativeDocumentsReceived: (p: unknown) => void }
      ).onNativeDocumentsReceived(c.value)
      expect(handler).not.toHaveBeenCalled()
      off()
    })
  }

  runResults('documents-received', documentsReceivedJson.consume as Section, () =>
    consumeReceivedDocuments()
  )
})

describe('layout events', () => {
  for (const c of (layoutJson.events as Section).valid ?? []) {
    it(`valid: ${c.name}`, () => {
      const seen: LayoutInfo[] = []
      const off = on('layoutChange', (l) => seen.push(l))
      ;(window as unknown as { onNativeLayoutChange: (l: unknown) => void }).onNativeLayoutChange(
        c.value
      )
      expect(seen).toEqual([c.value])
      off()
    })
  }
})

describe('back-requested', () => {
  const flush = async () => {
    for (let i = 0; i < 5; i++) await Promise.resolve()
  }
  const calls = (bridge: ReturnType<typeof installBridge>) =>
    (bridge.call as unknown as { mock: { calls: [string, unknown][] } }).mock.calls

  for (const c of (backRequestedJson.events as Section).valid ?? []) {
    for (const sample of (backRequestedJson.backResult as Section).valid ?? []) {
      it(`${c.name} request, answered "${sample.name}"`, async () => {
        const bridge = installBridge({ features: ALL_FEATURES })
        const sources: BackSource[] = []
        const off = onBackRequested((source) => {
          sources.push(source)
          return (sample.value as { handled: boolean }).handled
        })
        ;(
          window as unknown as { onNativeBackRequested: (p: unknown) => void }
        ).onNativeBackRequested(c.value)
        await flush()
        expect(sources).toEqual([(c.value as { source: BackSource }).source])
        expect(calls(bridge).at(-1)).toEqual(['backResult', sample.value])
        off()
      })
    }
  }

  it('sends the setBackInterception payloads of the fixture', () => {
    const bridge = installBridge({ features: ALL_FEATURES })
    onBackRequested(() => true)()
    const sent = calls(bridge)
      .filter(([action]) => action === 'setBackInterception')
      .map(([, payload]) => payload)
    expect(sent).toEqual(
      (backRequestedJson.setBackInterception as Section).valid?.map((c) => c.value)
    )
  })
})
