import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import {
  FEATURES,
  on,
  showContent,
  showDocument,
  showForm,
  updateDocument,
  updateSurface,
  type NativeFormField,
} from '../src/index.js'
import { installBridge as installUntyped, removeBridge } from './helpers.js'

afterEach(() => {
  vi.useRealTimers()
  removeBridge()
})

type Bridge = { call: Mock; postMessage: Mock }

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

const flush = async () => {
  for (let i = 0; i < 8; i++) await Promise.resolve()
}

/** The surface stays open until the test closes it; everything else answers `{ ok: true }`. */
function surfaceBridge(features: string[] = [...FEATURES]) {
  const surface = deferred<unknown>()
  const bridge = installUntyped({
    features,
    capabilities: ['nativeForms', 'nativeContent', 'customChrome'],
    call: vi.fn(async (action: string) =>
      action === 'showForm' || action === 'showContent' ? surface.promise : { ok: true }
    ),
  }) as unknown as Bridge
  const close = async () => surface.resolve({ ok: false, error: 'cancelled' })
  return { bridge, close }
}

const w = () => window as unknown as Record<string, ((e: unknown) => void) | undefined>

const sent = (bridge: Bridge, action: string) =>
  bridge.call.mock.calls.filter(([a]) => a === action).map(([, payload]) => payload)

describe('showForm with onChange', () => {
  const fields: NativeFormField[] = [
    { id: 'name', type: 'text' },
    { id: 'express', type: 'toggle', live: false },
    { id: 'note', type: 'info', value: 'read-only' },
  ]

  it('makes input fields live, assigns an id and hands changes to the handler', async () => {
    const { bridge, close } = surfaceBridge()
    const onChange = vi.fn()
    const pending = showForm({ fields }, { onChange })
    const [, payload] = bridge.call.mock.calls[0] as [
      string,
      { id: string; fields: NativeFormField[] },
    ]
    expect(typeof payload.id).toBe('string')
    expect(payload.fields).toEqual([
      { id: 'name', type: 'text', live: true },
      { id: 'express', type: 'toggle', live: false },
      { id: 'note', type: 'info', value: 'read-only' },
    ])
    w().onNativeSurfaceChange?.({ id: payload.id, fieldId: 'name', value: 'Mül' })
    w().onNativeSurfaceChange?.({ id: 'another-surface', fieldId: 'name', value: 'x' })
    expect(onChange).toHaveBeenCalledExactlyOnceWith('name', 'Mül')
    await close()
    await pending
    w().onNativeSurfaceChange?.({ id: payload.id, fieldId: 'name', value: 'late' })
    expect(onChange).toHaveBeenCalledOnce() // the surface is closed
  })

  it('marks the fields of every page', async () => {
    const { bridge, close } = surfaceBridge()
    const pending = showForm(
      {
        pages: [{ fields: [{ id: 'a', type: 'text' }] }, { fields: [{ id: 'b', type: 'number' }] }],
      },
      { onChange: () => {} }
    )
    const [, payload] = bridge.call.mock.calls[0] as [
      string,
      { pages: Array<{ fields: NativeFormField[] }> },
    ]
    expect(payload.pages.map((p) => p.fields[0]?.live)).toEqual([true, true])
    await close()
    await pending
  })

  it('does not touch a form without onChange', async () => {
    const { bridge, close } = surfaceBridge()
    const def = { fields: [{ id: 'name', type: 'text' as const }] }
    const pending = showForm(def)
    expect(bridge.call.mock.calls[0]).toEqual(['showForm', def])
    await close()
    await pending
  })

  it('is unavailable in an app without liveSurfaces, and does not ask it', async () => {
    const { bridge } = surfaceBridge(['menus'])
    expect(await showForm({ fields }, { onChange: () => {} })).toEqual({
      ok: false,
      error: 'unavailable',
    })
    expect(await showForm({ fields: [{ id: 'a', type: 'text', live: true }] })).toEqual({
      ok: false,
      error: 'unavailable',
    })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('is unavailable outside the app', async () => {
    expect(await showForm({ fields }, { onChange: () => {} })).toEqual({
      ok: false,
      error: 'unavailable',
    })
  })

  it('reports a handler that throws later, not into the app', async () => {
    vi.useFakeTimers()
    const { bridge, close } = surfaceBridge()
    const pending = showForm(
      { fields },
      {
        onChange: () => {
          throw new Error('boom')
        },
      }
    )
    const id = (bridge.call.mock.calls[0]?.[1] as { id: string }).id
    w().onNativeSurfaceChange?.({ id, fieldId: 'name', value: 1 })
    expect(() => vi.runAllTimers()).toThrow('boom')
    await close()
    await pending
  })
})

describe('showContent with onChange', () => {
  it('makes the fields blocks live, also inside cards', async () => {
    const { bridge, close } = surfaceBridge()
    const pending = showContent(
      {
        blocks: [
          { type: 'card', blocks: [{ type: 'fields', fields: [{ id: 'qty', type: 'stepper' }] }] },
        ],
      },
      { onChange: () => {} }
    )
    const [, payload] = bridge.call.mock.calls[0] as [
      string,
      { blocks: Array<{ blocks: Array<{ fields: NativeFormField[] }> }> },
    ]
    expect(payload.blocks[0]?.blocks[0]?.fields[0]).toEqual({
      id: 'qty',
      type: 'stepper',
      live: true,
    })
    await close()
    await pending
  })
})

describe('page search', () => {
  const search: NativeFormField = {
    id: 'customer',
    type: 'search',
    source: 'page',
    minQueryLength: 0,
  }

  async function open(onSearch: (fieldId: string, query: string) => unknown, features?: string[]) {
    const { bridge, close } = surfaceBridge(features)
    const pending = showForm({ fields: [search] }, { onSearch: onSearch as never })
    const id = (bridge.call.mock.calls[0]?.[1] as { id: string }).id
    const type = (query: string, requestId: string) =>
      w().onNativeSurfaceSearch?.({ id, fieldId: 'customer', query, requestId })
    return { bridge, close, pending, type }
  }

  it('answers a search with surfaceSearchResult', async () => {
    const onSearch = vi.fn(async () => [{ value: 'c1', label: 'Müller AG', subtitle: 'Zürich' }])
    const { bridge, close, pending, type } = await open(onSearch)
    type('mü', 'r1')
    await flush()
    expect(onSearch).toHaveBeenCalledWith('customer', 'mü')
    expect(sent(bridge, 'surfaceSearchResult')).toEqual([
      { requestId: 'r1', options: [{ value: 'c1', label: 'Müller AG', subtitle: 'Zürich' }] },
    ])
    await close()
    await pending
  })

  it('drops the answer to a request that a newer one replaced', async () => {
    const slow = deferred<Array<{ value: string; label: string }>>()
    const fast = deferred<Array<{ value: string; label: string }>>()
    const queue = [slow, fast]
    const { bridge, close, pending, type } = await open(() => queue.shift()!.promise)
    type('m', 'r1')
    type('mü', 'r2')
    fast.resolve([{ value: 'new', label: 'new' }])
    await flush()
    slow.resolve([{ value: 'old', label: 'old' }])
    await flush()
    expect(sent(bridge, 'surfaceSearchResult')).toEqual([
      { requestId: 'r2', options: [{ value: 'new', label: 'new' }] },
    ])
    await close()
    await pending
  })

  it('does not answer after the surface closed, and not on a failure', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const late = deferred<Array<{ value: string; label: string }>>()
    const { bridge, close, pending, type } = await open(() => late.promise)
    type('a', 'r1')
    await close()
    await pending
    late.resolve([{ value: 'x', label: 'x' }])
    await flush()
    expect(sent(bridge, 'surfaceSearchResult')).toEqual([])

    removeBridge()
    const failing = await open(async () => {
      throw new Error('offline')
    })
    failing.type('a', 'r1')
    await flush()
    expect(sent(failing.bridge, 'surfaceSearchResult')).toEqual([])
    await failing.close()
    await failing.pending
  })

  it('cuts to 50 options and leaves out images that are not https or a small data URI', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const many = Array.from({ length: 55 }, (_, k) => ({ value: `v${k}`, label: `Option ${k}` }))
    const { bridge, close, pending, type } = await open(() => [
      ...many,
      { value: 'http', label: 'h', image: 'http://example.com/a.png' },
    ])
    type('a', 'r1')
    await flush()
    const [{ options }] = sent(bridge, 'surfaceSearchResult') as [{ options: unknown[] }]
    expect(options).toHaveLength(50)
    await close()
    await pending

    removeBridge()
    const images = await open(() => [
      { value: 'ok', label: 'ok', image: 'https://example.com/a.png' },
      { value: 'data', label: 'data', image: 'data:image/png;base64,iVBORw0KGgo=' },
      { value: 'big', label: 'big', image: `data:image/png;base64,${'A'.repeat(200_000)}` },
      { value: 'http', label: 'http', image: 'http://example.com/a.png' },
    ])
    images.type('a', 'r1')
    await flush()
    const [{ options: shown }] = sent(images.bridge, 'surfaceSearchResult') as [
      { options: Array<{ value: string; image?: string }> },
    ]
    expect(shown.map((o) => [o.value, o.image !== undefined])).toEqual([
      ['ok', true],
      ['data', true],
      ['big', false],
      ['http', false],
    ])
    await images.close()
    await images.pending
  })

  it('is unavailable in an app without pageSearch', async () => {
    const { bridge } = surfaceBridge(['liveSurfaces'])
    expect(await showForm({ fields: [search] }, { onSearch: () => [] })).toEqual({
      ok: false,
      error: 'unavailable',
    })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('warns when onSearch and source: page do not belong together', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { close } = surfaceBridge()
    const a = showForm({ fields: [{ id: 'x', type: 'text' }] }, { onSearch: () => [] })
    expect(warn.mock.calls[0]?.[0]).toContain('source: "page"')
    const b = showForm({ fields: [search] })
    expect(warn.mock.calls[1]?.[0]).toContain('onSearch')
    await close()
    await Promise.all([a, b])
  })

  it('works for showContent as well', async () => {
    const { bridge, close } = surfaceBridge()
    const pending = showContent(
      { blocks: [{ type: 'fields', fields: [search] }] },
      { onSearch: () => [{ value: 'c', label: 'C' }] }
    )
    const id = (bridge.call.mock.calls[0]?.[1] as { id: string }).id
    w().onNativeSurfaceSearch?.({ id, fieldId: 'customer', query: 'c', requestId: 'r1' })
    await flush()
    expect(sent(bridge, 'surfaceSearchResult')).toHaveLength(1)
    await close()
    await pending
  })
})

describe('updateSurface', () => {
  it('sends only the keys that were given', async () => {
    const bridge = installUntyped({ features: [...FEATURES] }) as unknown as Bridge
    const update = {
      id: 'offer',
      title: 'Offer 4711',
      blocks: [{ type: 'heading' as const, id: 'h', text: 'Lines' }],
    }
    expect(await updateSurface(update)).toEqual({ ok: true })
    expect(bridge.call).toHaveBeenCalledWith('updateSurface', update)
  })

  it('passes notFound through', async () => {
    installUntyped({
      features: [...FEATURES],
      call: vi.fn(async () => ({ ok: false, error: 'notFound' })),
    })
    expect(await updateSurface({ id: 'gone', title: 'x' })).toEqual({
      ok: false,
      error: 'notFound',
    })
  })

  it.each([
    ['no id', { title: 'x' }],
    ['blocks not a list', { id: 'a', blocks: {} }],
    ['values not an object', { id: 'a', values: [] }],
    ['a number as title', { id: 'a', title: 3 }],
  ])('answers invalid without asking the app: %s', async (_name, update) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installUntyped({ features: [...FEATURES] }) as unknown as Bridge
    expect(await updateSurface(update as never)).toMatchObject({ ok: false, error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('warns about the limits of showForm and showContent in development builds, and still sends', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installUntyped({ features: [...FEATURES] }) as unknown as Bridge
    const fields = Array.from({ length: 61 }, (_, k) => ({ id: `f${k}`, type: 'text' as const }))
    await updateSurface({ id: 'f', fields })
    expect(warn.mock.calls.join('\n')).toContain('61 fields')
    expect(bridge.call).toHaveBeenCalledOnce()
  })

  it('makes new fields live when the surface was opened with onChange', async () => {
    const { bridge, close } = surfaceBridge()
    const pending = showForm(
      { id: 'f', fields: [{ id: 'a', type: 'text' }] },
      { onChange: () => {} }
    )
    await updateSurface({ id: 'f', fields: [{ id: 'b', type: 'text' }] })
    expect(sent(bridge, 'updateSurface')).toEqual([
      { id: 'f', fields: [{ id: 'b', type: 'text', live: true }] },
    ])
    await close()
    await pending
  })

  it('is unavailable outside the app and without the feature', async () => {
    expect(await updateSurface({ id: 'a', title: 'x' })).toEqual({
      ok: false,
      error: 'unavailable',
    })
    const bridge = installUntyped({ features: ['menus'] }) as unknown as Bridge
    expect(await updateSurface({ id: 'a', title: 'x' })).toEqual({
      ok: false,
      error: 'unavailable',
    })
    expect(bridge.call).not.toHaveBeenCalled()
  })
})

describe('showDocument and updateDocument', () => {
  const origin = () => window.location.origin
  const highlight = {
    id: 'l1',
    page: 1,
    x: 0.1,
    y: 0.4,
    w: 0.8,
    h: 0.05,
    style: 'primary' as const,
  }

  it('sends the absolute URL and resolves when the viewer is closed', async () => {
    const bridge = installUntyped({ features: [...FEATURES] }) as unknown as Bridge
    const res = await showDocument({
      id: 'pdf',
      url: '/api/offers/1/file',
      highlights: [highlight],
      selected: 'l1',
      page: 2,
    })
    expect(res).toEqual({ ok: true })
    expect(bridge.call).toHaveBeenCalledWith('showDocument', {
      id: 'pdf',
      url: `${origin()}/api/offers/1/file`,
      highlights: [highlight],
      selected: 'l1',
      page: 2,
    })
  })

  it('reports an HTTP failure with its status', async () => {
    installUntyped({
      features: [...FEATURES],
      call: vi.fn(async () => ({ ok: false, error: 'failed', status: 404 })),
    })
    expect(await showDocument({ url: '/missing.pdf' })).toEqual({
      ok: false,
      error: 'failed',
      status: 404,
    })
  })

  it.each([
    ['another host', { url: 'https://other.example.com/a.pdf' }],
    ['no url', {}],
    [
      '501 highlights',
      {
        url: '/a.pdf',
        highlights: Array.from({ length: 501 }, (_, k) => ({ ...highlight, id: `h${k}` })),
      },
    ],
    ['x above 1', { url: '/a.pdf', highlights: [{ ...highlight, x: 1.5 }] }],
    ['page 0', { url: '/a.pdf', highlights: [{ ...highlight, page: 0 }] }],
    ['an unknown style', { url: '/a.pdf', highlights: [{ ...highlight, style: 'x' }] }],
    ['the same highlight id twice', { url: '/a.pdf', highlights: [highlight, highlight] }],
  ])('answers invalid without asking the app: %s', async (_name, options) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installUntyped({ features: [...FEATURES] }) as unknown as Bridge
    expect(await showDocument(options as never)).toMatchObject({ ok: false, error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('warns about a selection that is not a highlight, and sends it', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installUntyped({ features: [...FEATURES] }) as unknown as Bridge
    await showDocument({ url: '/a.pdf', highlights: [highlight], selected: 'nope' })
    expect(warn.mock.calls[0]?.[0]).toContain('nope')
    expect(bridge.call).toHaveBeenCalledOnce()
  })

  it('updates the open viewer and passes notFound through', async () => {
    const bridge = installUntyped({ features: [...FEATURES] }) as unknown as Bridge
    expect(await updateDocument({ id: 'pdf', selected: 'l1', page: 3 })).toEqual({ ok: true })
    expect(bridge.call).toHaveBeenCalledWith('updateDocument', {
      id: 'pdf',
      selected: 'l1',
      page: 3,
    })
    removeBridge()
    installUntyped({
      features: [...FEATURES],
      call: vi.fn(async () => ({ ok: false, error: 'notFound' })),
    })
    expect(await updateDocument({ id: 'gone' })).toEqual({ ok: false, error: 'notFound' })
  })

  it('needs an id to update, and is unavailable outside the app', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    installUntyped({ features: [...FEATURES] })
    expect(await updateDocument({} as never)).toMatchObject({ error: 'invalid' })
    removeBridge()
    expect(await updateDocument({ id: 'x' })).toEqual({ ok: false, error: 'unavailable' })
    expect(await showDocument({ url: '/a.pdf' })).toEqual({ ok: false, error: 'unavailable' })
  })

  it('is unavailable without the feature', async () => {
    const bridge = installUntyped({ features: ['previewFile'] }) as unknown as Bridge
    expect(await showDocument({ url: '/a.pdf' })).toEqual({ ok: false, error: 'unavailable' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('delivers the tap and page events', () => {
    const taps: unknown[] = []
    const pages: unknown[] = []
    const offs = [on('documentTap', (e) => taps.push(e)), on('documentPage', (e) => pages.push(e))]
    w().onNativeDocumentTap?.({ id: 'pdf', highlightId: null, page: 2, x: 0.5, y: 0.5 })
    w().onNativeDocumentPage?.({ id: 'pdf', page: 3 })
    expect(taps).toEqual([{ id: 'pdf', highlightId: null, page: 2, x: 0.5, y: 0.5 }])
    expect(pages).toEqual([{ id: 'pdf', page: 3 }])
    offs.forEach((off) => off())
  })
})
