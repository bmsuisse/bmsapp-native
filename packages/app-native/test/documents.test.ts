import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  consumeReceivedDocuments,
  DOCUMENT_LIMITS,
  hasFeature,
  onDocumentsReceived,
  pickFiles,
  previewFile,
  scanDocument,
  type NativeDocument,
} from '../src/index.js'
import { installBridge, removeBridge } from './helpers.js'

afterEach(removeBridge)

const UPLOADED: NativeDocument = {
  name: 'offer.pdf',
  mime: 'application/pdf',
  size: 1234,
  pages: 2,
  uploadId: '8c2f1a4e-5b0a-4f3e-9d57-2b6f1c9e7a10',
  upload: { status: 200, body: { ok: true, id: 'doc-1' } },
}

function answer(result: unknown) {
  return vi.fn(async (_action: string, _payload?: Record<string, unknown>) => result)
}

describe('hasFeature', () => {
  it('is false outside the app and for an app without a list', () => {
    expect(hasFeature('pickFiles')).toBe(false)
    installBridge()
    expect(hasFeature('pickFiles')).toBe(false)
  })

  it('looks the name up in the list of the app', () => {
    installBridge({ features: ['pickFiles', 'layout'] })
    expect(hasFeature('pickFiles')).toBe(true)
    expect(hasFeature('dictate')).toBe(false)
  })

  it('ignores a list that is not a list', () => {
    installBridge({ features: 'pickFiles' as never })
    expect(hasFeature('pickFiles')).toBe(false)
  })
})

describe('scanDocument', () => {
  it('without options sends what it always sent and returns the documents', async () => {
    const bridge = installBridge({
      features: ['scanResult'],
      call: answer({ ok: true, documents: [UPLOADED] }),
    })
    expect(await scanDocument()).toEqual({ ok: true, documents: [UPLOADED] })
    expect(bridge.call).toHaveBeenCalledWith('scanDocument', {})
  })

  it('sends the options that were given', async () => {
    const bridge = installBridge({
      features: ['scanResult', 'scanOptions'],
      call: answer({ ok: true, documents: [UPLOADED] }),
    })
    await scanDocument({ kind: 'offer', mode: 'return', multiple: true, context: { offerId: 7 } })
    expect(bridge.call).toHaveBeenCalledWith('scanDocument', {
      kind: 'offer',
      mode: 'return',
      multiple: true,
      context: { offerId: 7 },
    })
  })

  it('treats null as no context', async () => {
    const bridge = installBridge({
      features: ['scanResult', 'scanOptions'],
      call: answer({ ok: true, documents: [UPLOADED] }),
    })
    await scanDocument({ context: null as never })
    expect(bridge.call).toHaveBeenCalledWith('scanDocument', {})
  })

  it('reports an app that predates the result as oldApp', async () => {
    installBridge()
    expect(await scanDocument()).toEqual({ ok: true, documents: [], oldApp: true })
  })

  it('does not scan with options an app without scanOptions would ignore', async () => {
    const bridge = installBridge({ features: ['scanResult'] })
    for (const options of [
      { mode: 'return' },
      { multiple: true },
      { kind: 'offer' },
      { context: {} },
    ] as const) {
      expect(await scanDocument(options)).toMatchObject({ ok: false, error: 'unavailable' })
    }
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('still scans when the options are the defaults', async () => {
    const bridge = installBridge({ call: answer({ ok: true }) })
    await scanDocument({ mode: 'upload', kind: 'scan', multiple: false })
    expect(bridge.call).toHaveBeenCalledOnce()
  })

  it.each([
    ['context too large', { context: { text: 'x'.repeat(4097) } }],
    ['context an array', { context: [] }],
    ['kind with capitals', { kind: 'Offer' }],
    ['kind empty', { kind: '' }],
    ['kind too long', { kind: 'a'.repeat(33) }],
    ['mode unknown', { mode: 'save' }],
    ['multiple not a boolean', { multiple: 'yes' }],
  ])('answers invalid without asking the app: %s', async (_name, options) => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge({ features: ['scanResult', 'scanOptions'] })
    const res = await scanDocument(options as never)
    expect(res).toMatchObject({ ok: false, error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
    expect(warn).toHaveBeenCalledOnce()
  })

  it('accepts a context of exactly 4096 bytes and counts bytes, not characters', async () => {
    const bridge = installBridge({
      features: ['scanResult', 'scanOptions'],
      call: answer({ ok: true, documents: [UPLOADED] }),
    })
    // {"t":"…"} has 8 bytes of JSON around the text.
    const fits = { t: 'x'.repeat(4096 - 8) }
    expect((await scanDocument({ context: fits })).ok).toBe(true)
    const umlauts = { t: 'ä'.repeat(2045) } // 4090 bytes of text, 4098 serialized
    expect(await scanDocument({ context: umlauts })).toMatchObject({ error: 'invalid' })
    expect(bridge.call).toHaveBeenCalledOnce()
  })

  it('does not warn in a production bundle', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    installBridge()
    await scanDocument({ kind: 'NO' })
    expect(warn).not.toHaveBeenCalled()
  })

  it.each(['cancelled', 'capability', 'unavailable', 'invalid'])(
    'passes %s through',
    async (error) => {
      installBridge({ features: ['scanResult'], call: answer({ ok: false, error }) })
      expect(await scanDocument()).toEqual({ ok: false, error })
    }
  )

  it('keeps failed documents of a batch', async () => {
    const failed: NativeDocument = { name: 'b.pdf', uploadId: 'u-2', error: 'failed' }
    installBridge({
      features: ['scanResult', 'scanOptions'],
      call: answer({ ok: true, documents: [UPLOADED, failed] }),
    })
    const res = await scanDocument({ multiple: true })
    expect(res).toEqual({ ok: true, documents: [UPLOADED, failed] })
  })

  it.each([
    ['no documents', { ok: true, documents: [] }],
    ['not a list', { ok: true, documents: 'x' }],
    ['a document without uploadId', { ok: true, documents: [{ name: 'a', mime: 'x', size: 1 }] }],
    ['a document without size', { ok: true, documents: [{ name: 'a', mime: 'x', uploadId: 'u' }] }],
  ])('reports an unexpected answer as failed: %s', async (_name, result) => {
    installBridge({ features: ['scanResult'], call: answer(result) })
    expect(await scanDocument()).toMatchObject({ ok: false, error: 'failed' })
  })

  it('is unavailable outside the app and for unknownAction', async () => {
    expect(await scanDocument()).toEqual({ ok: false, error: 'unavailable' })
    installBridge({ call: answer({ ok: false, error: 'unknownAction' }) })
    expect(await scanDocument()).toEqual({ ok: false, error: 'unknownAction' })
  })

  it('never throws', async () => {
    installBridge({
      call: vi.fn(async () => {
        throw new Error('boom')
      }),
    })
    expect(await scanDocument()).toEqual({ ok: false, error: 'unavailable' })
  })
})

describe('pickFiles in the app', () => {
  it('sends only what was given and returns the documents', async () => {
    const bridge = installBridge({
      features: ['pickFiles'],
      call: answer({ ok: true, documents: [UPLOADED] }),
    })
    const res = await pickFiles({
      sources: ['files', 'photos'],
      accept: ['application/pdf', '.eml'],
      multiple: true,
      mode: 'upload',
      kind: 'offer',
      context: { a: 1 },
    })
    expect(res).toEqual({ ok: true, documents: [UPLOADED] })
    expect(bridge.call).toHaveBeenCalledWith('pickFiles', {
      sources: ['files', 'photos'],
      accept: ['application/pdf', '.eml'],
      multiple: true,
      mode: 'upload',
      kind: 'offer',
      context: { a: 1 },
    })
    await pickFiles({ sources: ['camera'] })
    expect(bridge.call).toHaveBeenLastCalledWith('pickFiles', { sources: ['camera'] })
  })

  it.each([
    ['no sources', { sources: [] }],
    ['sources missing', {}],
    ['unknown source', { sources: ['cloud'] }],
    ['accept not a list', { sources: ['files'], accept: '.pdf' }],
    ['accept with a number', { sources: ['files'], accept: [1] }],
    ['multiple not boolean', { sources: ['files'], multiple: 1 }],
    ['mode unknown', { sources: ['files'], mode: 'x' }],
    ['kind invalid', { sources: ['files'], kind: 'A B' }],
    ['context too large', { sources: ['files'], context: { t: 'x'.repeat(5000) } }],
  ])('answers invalid without asking the app: %s', async (_name, options) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge({ features: ['pickFiles'] })
    expect(await pickFiles(options as never)).toMatchObject({ ok: false, error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('is unavailable in an app without the feature', async () => {
    const bridge = installBridge()
    expect(await pickFiles({ sources: ['files'] })).toEqual({ ok: false, error: 'unavailable' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('treats unknownAction as unavailable and passes capability and cancelled', async () => {
    installBridge({ features: ['pickFiles'], call: answer({ ok: false, error: 'unknownAction' }) })
    expect(await pickFiles({ sources: ['files'] })).toEqual({ ok: false, error: 'unknownAction' })
    removeBridge()
    installBridge({ features: ['pickFiles'], call: answer({ ok: false, error: 'capability' }) })
    expect(await pickFiles({ sources: ['camera'] })).toEqual({ ok: false, error: 'capability' })
  })
})

describe('pickFiles in the browser', () => {
  function pickWith(files: File[] | 'cancel', options: Parameters<typeof pickFiles>[0]) {
    const click = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(function (
      this: HTMLInputElement
    ) {
      queueMicrotask(() => {
        if (files === 'cancel') return this.dispatchEvent(new Event('cancel'))
        Object.defineProperty(this, 'files', { value: files, configurable: true })
        this.dispatchEvent(new Event('change'))
      })
    })
    const result = pickFiles(options)
    return { result, input: () => click.mock.contexts[0] as HTMLInputElement | undefined }
  }

  it('reads the file as base64 data', async () => {
    const file = new File(['hello'], 'note.txt', { type: 'text/plain' })
    const { result, input } = pickWith([file], { sources: ['files'], accept: ['.txt'] })
    const res = await result
    expect(res.ok).toBe(true)
    if (!res.ok) return
    expect(res.documents).toHaveLength(1)
    expect(res.documents[0]).toMatchObject({
      name: 'note.txt',
      mime: 'text/plain',
      size: 5,
      data: btoa('hello'),
    })
    expect(res.documents[0]?.uploadId).toMatch(/^[0-9a-f-]{36}$/)
    expect(input()?.accept).toBe('.txt')
    expect(input()?.isConnected).toBe(false) // cleaned up
  })

  it('sets multiple, and capture for the camera only, and images for photos', async () => {
    const file = new File(['x'], 'a.jpg', { type: 'image/jpeg' })
    const camera = pickWith([file], { sources: ['camera'], multiple: true })
    await camera.result
    expect(camera.input()?.multiple).toBe(true)
    expect(camera.input()?.getAttribute('capture')).toBe('environment')
    expect(camera.input()?.accept).toBe('image/*')
    vi.restoreAllMocks()
    const mixed = pickWith([file], { sources: ['files', 'camera'] })
    await mixed.result
    expect(mixed.input()?.hasAttribute('capture')).toBe(false)
    expect(mixed.input()?.accept).toBe('')
  })

  it('gives each file its own uploadId and marks files over the limit as tooLarge', async () => {
    const a = new File(['a'], 'a.txt', { type: 'text/plain' })
    const big = new File(['b'], 'big.pdf', { type: 'application/pdf' })
    Object.defineProperty(big, 'size', { value: DOCUMENT_LIMITS.bytes + 1 })
    const res = await pickWith([a, big], { sources: ['files'], multiple: true }).result
    expect(res.ok).toBe(true)
    if (!res.ok) return
    const [first, second] = res.documents
    expect(first?.uploadId).not.toBe(second?.uploadId)
    expect(second).toMatchObject({
      name: 'big.pdf',
      error: 'tooLarge',
      size: DOCUMENT_LIMITS.bytes + 1,
    })
    expect(second?.data).toBeUndefined()
  })

  it('uses octet-stream for a file without a type', async () => {
    const res = await pickWith([new File(['x'], 'mail.eml')], { sources: ['files'] }).result
    expect(res.ok && res.documents[0]?.mime).toBe('application/octet-stream')
  })

  it('reports a cancelled dialog and an empty selection as cancelled', async () => {
    expect(await pickWith('cancel', { sources: ['files'] }).result).toEqual({
      ok: false,
      error: 'cancelled',
    })
    vi.restoreAllMocks()
    expect(await pickWith([], { sources: ['files'] }).result).toEqual({
      ok: false,
      error: 'cancelled',
    })
  })

  it('has no upload mode', async () => {
    const click = vi.spyOn(HTMLInputElement.prototype, 'click')
    expect(await pickFiles({ sources: ['files'], mode: 'upload' })).toEqual({
      ok: false,
      error: 'unavailable',
    })
    expect(click).not.toHaveBeenCalled()
  })

  it('answers invalid before opening any dialog', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const click = vi.spyOn(HTMLInputElement.prototype, 'click')
    expect(await pickFiles({ sources: [] })).toMatchObject({ error: 'invalid' })
    expect(click).not.toHaveBeenCalled()
  })
})

describe('onDocumentsReceived and consumeReceivedDocuments', () => {
  const batch = { documents: [UPLOADED] }
  const flush = () => new Promise((resolve) => setTimeout(resolve))
  const received = () =>
    (window as unknown as { onNativeDocumentsReceived?: unknown }).onNativeDocumentsReceived

  it('sets the handler first, then consumes once and hands over the queued batch', async () => {
    let installedWhenAsked: unknown
    const bridge = installBridge({
      features: ['receiveDocuments'],
      call: vi.fn(async () => {
        installedWhenAsked = received()
        return { ok: true, documents: [UPLOADED] }
      }),
    })
    const handler = vi.fn()
    const off = onDocumentsReceived(handler)
    await flush()
    expect(typeof installedWhenAsked).toBe('function')
    expect(bridge.call).toHaveBeenCalledTimes(1)
    expect(bridge.call).toHaveBeenCalledWith('consumeReceivedDocuments', {})
    expect(handler).toHaveBeenCalledOnce()
    expect(handler).toHaveBeenCalledWith(batch)
    off()
  })

  it('does not call the handler for an empty queue', async () => {
    installBridge({ features: ['receiveDocuments'], call: answer({ ok: true, documents: [] }) })
    const handler = vi.fn()
    const off = onDocumentsReceived(handler)
    await flush()
    expect(handler).not.toHaveBeenCalled()
    off()
  })

  it('delivers batches the app calls the page with, to every handler', async () => {
    installBridge({ features: ['receiveDocuments'], call: answer({ ok: true, documents: [] }) })
    const a = vi.fn()
    const b = vi.fn()
    const offA = onDocumentsReceived(a)
    const offB = onDocumentsReceived(b)
    ;(received() as (p: unknown) => void)(batch)
    expect(a).toHaveBeenCalledWith(batch)
    expect(b).toHaveBeenCalledWith(batch)
    offA()
    ;(received() as (p: unknown) => void)(batch)
    expect(a).toHaveBeenCalledOnce()
    expect(b).toHaveBeenCalledTimes(2)
    offB()
  })

  it('removes window.onNativeDocumentsReceived with the last handler, so the app queues again', async () => {
    installBridge({ features: ['receiveDocuments'], call: answer({ ok: true, documents: [] }) })
    expect(received()).toBeUndefined()
    const off = onDocumentsReceived(() => {})
    const off2 = onDocumentsReceived(() => {})
    expect(typeof received()).toBe('function')
    off()
    expect(typeof received()).toBe('function')
    off2()
    off2() // twice is harmless
    expect(received()).toBeUndefined()
  })

  it('restores a function the page had set and still calls it', async () => {
    installBridge({ features: ['receiveDocuments'], call: answer({ ok: true, documents: [] }) })
    const own = vi.fn()
    ;(window as unknown as Record<string, unknown>).onNativeDocumentsReceived = own
    const off = onDocumentsReceived(() => {})
    ;(received() as (p: unknown) => void)(batch)
    expect(own).toHaveBeenCalledWith(batch)
    off()
    expect(received()).toBe(own)
    delete (window as unknown as Record<string, unknown>).onNativeDocumentsReceived
  })

  it('does not hand a queued batch to a handler that was removed meanwhile', async () => {
    installBridge({
      features: ['receiveDocuments'],
      call: answer({ ok: true, documents: [UPLOADED] }),
    })
    const handler = vi.fn()
    onDocumentsReceived(handler)()
    await flush()
    expect(handler).not.toHaveBeenCalled()
  })

  it('does not ask the app without the feature, and never throws', async () => {
    const bridge = installBridge()
    const handler = vi.fn()
    const off = onDocumentsReceived(handler)
    await flush()
    expect(bridge.call).not.toHaveBeenCalled()
    off()
    expect(await consumeReceivedDocuments()).toEqual({ ok: false, error: 'unavailable' })
  })

  it('consumeReceivedDocuments is unavailable in the browser and for unknownAction', async () => {
    expect(await consumeReceivedDocuments()).toEqual({ ok: false, error: 'unavailable' })
    installBridge({
      features: ['receiveDocuments'],
      call: answer({ ok: false, error: 'unknownAction' }),
    })
    expect(await consumeReceivedDocuments()).toEqual({ ok: false, error: 'unknownAction' })
  })

  it('consumeReceivedDocuments returns the queue, possibly empty', async () => {
    installBridge({ features: ['receiveDocuments'], call: answer({ ok: true, documents: [] }) })
    expect(await consumeReceivedDocuments()).toEqual({ ok: true, documents: [] })
  })
})

describe('previewFile', () => {
  const origin = () => window.location.origin

  it('sends the absolute url on the own origin and the filename', async () => {
    const bridge = installBridge({ features: ['previewFile'], call: answer({ ok: true }) })
    expect(await previewFile({ url: '/files/a.pdf', filename: 'Offer.pdf' })).toEqual({ ok: true })
    expect(bridge.call).toHaveBeenCalledWith('previewFile', {
      url: `${origin()}/files/a.pdf`,
      filename: 'Offer.pdf',
    })
    await previewFile({ url: `${origin()}/b.pdf` })
    expect(bridge.call).toHaveBeenLastCalledWith('previewFile', { url: `${origin()}/b.pdf` })
  })

  it.each([
    ['another host', 'https://evil.example.com/a.pdf'],
    ['a protocol-relative url to another host', '//evil.example.com/a.pdf'],
    ['a data url', 'data:text/plain,hi'],
    ['empty', ''],
  ])('answers invalid for %s without asking the app', async (_name, url) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge({ features: ['previewFile'] })
    expect(await previewFile({ url })).toMatchObject({ ok: false, error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('rejects a filename that is not a string', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    installBridge({ features: ['previewFile'] })
    expect(await previewFile({ url: '/a', filename: 3 as never })).toMatchObject({
      error: 'invalid',
    })
  })

  it('reports an HTTP failure with its status', async () => {
    installBridge({
      features: ['previewFile'],
      call: answer({ ok: false, error: 'failed', status: 404 }),
    })
    expect(await previewFile({ url: '/missing.pdf' })).toEqual({
      ok: false,
      error: 'failed',
      status: 404,
    })
  })

  it('is unavailable in an app without the feature or answering unknownAction', async () => {
    installBridge()
    expect(await previewFile({ url: '/a.pdf' })).toEqual({ ok: false, error: 'unavailable' })
    removeBridge()
    installBridge({
      features: ['previewFile'],
      call: answer({ ok: false, error: 'unknownAction' }),
    })
    expect(await previewFile({ url: '/a.pdf' })).toEqual({ ok: false, error: 'unknownAction' })
  })

  it('opens a new tab in the browser', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    expect(await previewFile({ url: '/a.pdf' })).toEqual({ ok: true })
    expect(open).toHaveBeenCalledWith(`${origin()}/a.pdf`, '_blank', 'noopener')
  })
})
