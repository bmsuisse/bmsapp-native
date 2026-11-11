// Final alignment 2026-11c: one test per change and per verified/fixed decision (D1-D22).

import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import {
  CHROME_LIMITS,
  DOCUMENT_LIMITS,
  FEATURES,
  chromeLimitWarnings,
  consumeReceivedDocuments,
  dictate,
  getAccessToken,
  getLayout,
  isNativeSurfaceUnsupported,
  isUnavailable,
  onBackRequested,
  pickFiles,
  previewFile,
  scanDocument,
  setChrome,
  setKeyCommands,
  setKeyboardToolbar,
  showAlert,
  showContent,
  showDocument,
  showForm,
  showMenu,
  showPicker,
  toast,
  updateDocument,
  updateSurface,
  type NativeFormField,
  type NativeMenuSection,
} from '../src/index.js'
import { installBridge as installUntyped, removeBridge } from './helpers.js'

afterEach(() => {
  vi.useRealTimers()
  removeBridge()
})

type Bridge = { call: Mock; postMessage: Mock }

function install(overrides: Parameters<typeof installUntyped>[0] = {}) {
  return installUntyped({
    features: [...FEATURES],
    capabilities: ['customChrome', 'camera', 'nativeForms', 'nativeContent', 'identity'],
    ...overrides,
  }) as unknown as Bridge
}

const answer = (result: unknown) =>
  vi.fn(async (_action: string, _payload?: Record<string, unknown>) => result)

const flush = async () => {
  for (let i = 0; i < 8; i++) await Promise.resolve()
}

const w = () => window as unknown as Record<string, ((e: unknown) => void) | undefined>
const ANCHOR = { x: 1, y: 2, width: 3, height: 4 }

// --- D10 / change 1: dictate maxSeconds is a whole number -----------------------------

describe('D10: dictate maxSeconds', () => {
  it.each([30.5, 0.5, 1.0000001, 120.5])('%s is invalid and the app is not asked', async (n) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = install()
    expect(await dictate({ maxSeconds: n })).toMatchObject({ ok: false, error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it.each([1, 60, 120])('%s is sent', async (n) => {
    const bridge = install({ call: answer({ ok: true, text: '', locale: 'de' }) })
    await dictate({ maxSeconds: n })
    expect(bridge.call).toHaveBeenCalledWith('dictate', { maxSeconds: n })
  })

  it('an unsupported locale is the answer "unavailable" of the app, passed through', async () => {
    install({ call: answer({ ok: false, error: 'unavailable' }) })
    expect(await dictate({ locale: 'xx-XX' })).toEqual({ ok: false, error: 'unavailable' })
  })
})

// --- D14 / change 2: live only on scalar fields ------------------------------------------

describe('D14: live only on scalar field types', () => {
  const fields: NativeFormField[] = [
    { id: 'name', type: 'text' },
    { id: 'qty', type: 'stepper' },
    { id: 'card', type: 'search' },
    { id: 'photo', type: 'photo' },
    { id: 'pages', type: 'scan' },
    { id: 'sig', type: 'signature' },
    { id: 'rows', type: 'repeat', fields: [{ id: 'a', type: 'text' }] },
    { id: 'hint', type: 'info', value: 'x' },
  ]

  function open(def: () => Promise<unknown>) {
    let finish!: (value: unknown) => void
    const bridge = install({
      call: vi.fn(async (action: string) =>
        action === 'showForm' || action === 'showContent'
          ? new Promise((resolve) => (finish = resolve))
          : { ok: true }
      ),
    })
    const pending = def()
    return { bridge, close: async () => (finish({ ok: false, error: 'cancelled' }), pending) }
  }

  it('onChange marks the scalar fields only', async () => {
    const { bridge, close } = open(() => showForm({ fields }, { onChange: () => {} }))
    const [, payload] = bridge.call.mock.calls[0] as [string, { fields: NativeFormField[] }]
    expect(payload.fields.map((f) => [f.id, f.live === true])).toEqual([
      ['name', true],
      ['qty', true],
      ['card', true],
      ['photo', false],
      ['pages', false],
      ['sig', false],
      ['rows', false],
      ['hint', false],
    ])
    await close()
  })

  it('removes a live that the page set on a field that cannot be live', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { bridge, close } = open(() =>
      showForm({ fields: [{ id: 'photo', type: 'photo', live: true }] })
    )
    const [, payload] = bridge.call.mock.calls[0] as [string, { fields: NativeFormField[] }]
    expect('live' in (payload.fields[0] ?? {})).toBe(false)
    expect(warn.mock.calls[0]?.[0]).toContain('only scalar fields')
    await close()
  })

  it('does not count a removed live as a need for the feature', async () => {
    const bridge = install({ features: [], call: answer({ ok: false, error: 'cancelled' }) })
    await showForm({ fields: [{ id: 'photo', type: 'photo', live: true }] })
    expect(bridge.call).toHaveBeenCalledOnce() // not "unavailable": nothing live is left
  })

  it('applies to the fields blocks of content and to updateSurface', async () => {
    const { bridge, close } = open(() =>
      showContent(
        { id: 'c', blocks: [{ type: 'fields', fields: [fields[0]!, fields[3]!] }] },
        { onChange: () => {} }
      )
    )
    const [, payload] = bridge.call.mock.calls[0] as [
      string,
      { blocks: Array<{ fields: NativeFormField[] }> },
    ]
    expect(payload.blocks[0]?.fields.map((f) => f.live)).toEqual([true, undefined])
    await updateSurface({ id: 'c', blocks: [{ type: 'fields', fields: [fields[1]!, fields[4]!] }] })
    const update = bridge.call.mock.calls.find(([a]) => a === 'updateSurface')?.[1] as {
      blocks: Array<{ fields: NativeFormField[] }>
    }
    expect(update.blocks[0]?.fields.map((f) => f.live)).toEqual([true, undefined])
    await close()
  })
})

describe('D14: ids are unique per surface', () => {
  it('updateSurface refuses duplicate field, block and list item ids', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = install()
    const text: NativeFormField = { id: 'a', type: 'text' }
    expect(await updateSurface({ id: 's', fields: [text, text] })).toMatchObject({
      error: 'invalid',
    })
    expect(
      await updateSurface({
        id: 's',
        blocks: [
          { type: 'divider', id: 'x' },
          { type: 'divider', id: 'x' },
        ],
      })
    ).toMatchObject({ error: 'invalid' })
    expect(
      await updateSurface({
        id: 's',
        blocks: [
          {
            type: 'list',
            items: [
              { id: 'l', title: 'a' },
              { id: 'l', title: 'b' },
            ],
          },
        ],
      })
    ).toMatchObject({ error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('a block and a field may share an id (unique per kind)', async () => {
    const bridge = install()
    await updateSurface({
      id: 's',
      blocks: [
        { type: 'heading', id: 'a', text: 'x' },
        { type: 'fields', fields: [{ id: 'a', type: 'text' }] },
      ],
    })
    expect(bridge.call).toHaveBeenCalledOnce()
  })
})

// --- D3 / change 3: unknownAction is kept and treated like unavailable --------------------

describe('D3: unknownAction keeps its code and counts as unavailable', () => {
  const unknown = () => answer({ ok: false, error: 'unknownAction' })
  const calls: Array<[string, () => Promise<{ ok: boolean; error?: unknown }>]> = [
    ['scanDocument', () => scanDocument()],
    ['pickFiles', () => pickFiles({ sources: ['files'] })],
    ['consumeReceivedDocuments', () => consumeReceivedDocuments()],
    ['previewFile', () => previewFile({ url: '/a.pdf' })],
    ['dictate', () => dictate()],
    ['getLayout', () => getLayout()],
    ['getAccessToken', () => getAccessToken({ resource: 'api://x/.default' })],
    [
      'showMenu',
      () => showMenu({ anchor: ANCHOR, sections: [{ items: [{ id: 'a', label: 'A' }] }] }),
    ],
    ['showAlert', () => showAlert({ title: 'T', actions: [{ id: 'a', label: 'A' }] })],
    ['toast', () => toast('x', { duration: 2 })],
    ['showPicker', () => showPicker({ kind: 'date' })],
    ['updateSurface', () => updateSurface({ id: 's', title: 'x' })],
    ['setKeyboardToolbar', () => setKeyboardToolbar({ items: [] })],
    ['setKeyCommands', () => setKeyCommands({ commands: [] })],
    ['showDocument', () => showDocument({ url: '/a.pdf' })],
    ['updateDocument', () => updateDocument({ id: 'd' })],
  ]

  it.each(calls)('%s', async (_name, run) => {
    install({ call: unknown() })
    const res = await run()
    expect(res).toMatchObject({ ok: false, error: 'unknownAction' })
    expect(isUnavailable(res)).toBe(true)
  })

  it('isUnavailable and isNativeSurfaceUnsupported treat both codes alike', () => {
    expect(isUnavailable({ ok: false, error: 'unavailable' })).toBe(true)
    expect(isUnavailable({ ok: false, error: 'unknownAction' })).toBe(true)
    expect(isUnavailable({ ok: false, error: 'cancelled' })).toBe(false)
    expect(isUnavailable({ ok: true })).toBe(false)
    expect(isNativeSurfaceUnsupported({ ok: false, error: 'unknownAction' })).toBe(true)
  })

  it('the package itself answers "unavailable" when the feature is not listed', async () => {
    const bridge = install({ features: [] })
    expect(await dictate()).toEqual({ ok: false, error: 'unavailable' })
    expect(bridge.call).not.toHaveBeenCalled()
  })
})

// --- D15 / change 4: lazy children are rejected in the menus of the bar -------------------------

describe('D15: lazy children only in showMenu', () => {
  const lazy: NativeMenuSection[] = [{ items: [{ id: 'a', label: 'A', children: 'lazy' }] }]
  const plain: NativeMenuSection[] = [{ items: [{ id: 'b', label: 'B' }] }]
  const posted = (bridge: Bridge) =>
    bridge.postMessage.mock.calls.at(-1)?.[0] as {
      title: unknown
      actionButtons: unknown[]
    }

  it('leaves a lazy title menu out and sends the title', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = install()
    setChrome({ title: { text: 'T', subtitle: 's', menu: lazy } })
    expect(posted(bridge).title).toEqual({ text: 'T', subtitle: 's' })
  })

  it('leaves a lazy action button menu out, the button then fires the tap', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = install()
    setChrome({
      actionButtons: [
        { id: 'one', icon: 'i', menu: lazy },
        { id: 'two', icon: 'i', menu: plain },
      ],
    })
    const buttons = posted(bridge).actionButtons
    expect(buttons[0]).toEqual({ id: 'one', icon: 'i' })
    expect(buttons[1]).toEqual({ id: 'two', icon: 'i', menu: plain })
  })

  it('finds a lazy item below the first level', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = install()
    const deep: NativeMenuSection[] = [{ items: [{ id: 'p', label: 'P', children: lazy }] }]
    setChrome({ title: { text: 'T', menu: deep } })
    expect(posted(bridge).title).toEqual({ text: 'T' })
  })

  it('showMenu still takes lazy items', async () => {
    const bridge = install({ call: answer({ ok: false, error: 'cancelled' }) })
    await showMenu({ anchor: ANCHOR, sections: lazy, loadChildren: () => plain })
    expect(bridge.call).toHaveBeenCalledOnce()
  })
})

// --- D1: name and payload stay separate --------------------------------------------------------

describe('D1: BMSNative.call(name, payload) never flattens', () => {
  it('toast keeps action:{id,label} as payload, and nothing is posted', async () => {
    const bridge = install({ call: answer({ ok: true, toastId: 't' }) })
    await toast('Deleted', { action: { id: 'undo', label: 'Undo' } })
    expect(bridge.call).toHaveBeenCalledExactlyOnceWith('toast', {
      message: 'Deleted',
      action: { id: 'undo', label: 'Undo' },
    })
    expect(bridge.postMessage).not.toHaveBeenCalled()
  })
})

// --- D2: every feature is gated; the package answers unavailable itself ---------------------------

describe('D2: a call for an unlisted feature is never forwarded', () => {
  it('none of the calls reaches an app with an empty feature list', async () => {
    const bridge = install({ features: [] })
    const results = await Promise.all([
      scanDocument({ mode: 'return' }),
      pickFiles({ sources: ['files'] }),
      consumeReceivedDocuments(),
      previewFile({ url: '/a.pdf' }),
      dictate(),
      getLayout(),
      getAccessToken({ resource: 'api://x/.default' }),
      showMenu({ anchor: ANCHOR, sections: [{ items: [{ id: 'a', label: 'A' }] }] }),
      showAlert({ title: 'T', actions: [{ id: 'a', label: 'A' }] }),
      toast('x', { duration: 2 }),
      showPicker({ kind: 'date' }),
      updateSurface({ id: 's', title: 'x' }),
      setKeyboardToolbar({ items: [] }),
      setKeyCommands({ commands: [] }),
      showDocument({ url: '/a.pdf' }),
      updateDocument({ id: 'd' }),
      showForm({ fields: [{ id: 'a', type: 'text', live: true }] }),
      showForm({ fields: [{ id: 'a', type: 'search', source: 'page' }] }),
    ])
    for (const res of results) expect(res).toMatchObject({ ok: false, error: 'unavailable' })
    onBackRequested(() => true)()
    expect(bridge.call).not.toHaveBeenCalled()
    expect(bridge.postMessage).not.toHaveBeenCalled()
  })

  it('setChrome leaves out each part whose feature is missing, and sends the rest', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const chrome = {
      scope: 'route' as const,
      title: { text: 'T' },
      search: { id: 's', placeholder: 'p' },
      segments: {
        id: 'v',
        items: [
          { id: 'a', label: 'A' },
          { id: 'b', label: 'B' },
        ],
        selected: 'a',
      },
      sidebar: { title: 'S', sections: [] },
      undo: { canUndo: true, canRedo: false },
      actionButtons: [{ id: 'm', icon: 'i', menu: [{ items: [{ id: 'x', label: 'X' }] }] }],
    }
    const parts: Array<[string, string]> = [
      ['title', 'titleMenu'],
      ['search', 'navSearch'],
      ['segments', 'segments'],
      ['sidebar', 'sidebar'],
      ['undo', 'undoGestures'],
    ]
    for (const [key, feature] of parts) {
      const bridge = install({ features: FEATURES.filter((f) => f !== feature) })
      setChrome(chrome)
      const sent = bridge.postMessage.mock.calls[0]?.[0] as Record<string, unknown>
      expect(key in sent).toBe(false)
      expect(
        Object.keys(sent)
          .filter((k) => k !== 'action' && k !== key)
          .sort()
      ).toEqual(
        ['actionButtons', 'scope', ...parts.map(([k]) => k).filter((k) => k !== key)].sort()
      )
      removeBridge()
    }
    const bridge = install({ features: FEATURES.filter((f) => f !== 'menus') })
    setChrome(chrome)
    const buttons = (bridge.postMessage.mock.calls[0]?.[0] as typeof chrome).actionButtons
    expect(buttons).toEqual([{ id: 'm', icon: 'i' }])
  })

  it('setChrome sends nothing when only unlisted parts were given', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = install({ features: [] })
    setChrome({ search: { id: 's', placeholder: 'p' } })
    expect(bridge.postMessage).not.toHaveBeenCalled()
    setChrome({}) // an explicit empty chrome is the page's wish: it is sent
    expect(bridge.postMessage).toHaveBeenCalledOnce()
  })

  it('answers from the app (menuItems, surfaceSearchResult, backResult) are gated as well', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    // The events arrive although the app does not list the features: nothing is answered.
    let finishMenu!: (v: unknown) => void
    const bridge = install({
      features: ['menus'],
      call: vi.fn(async (action: string) =>
        action === 'showMenu' ? new Promise((r) => (finishMenu = r)) : { ok: true }
      ),
    })
    const lazy = [{ items: [{ id: 'a', label: 'A', children: 'lazy' as const }] }]
    const shown = showMenu({
      id: 'm',
      anchor: ANCHOR,
      sections: lazy,
      loadChildren: () => [{ items: [{ id: 'b', label: 'B' }] }],
    })
    w().onNativeMenuExpand?.({ menuId: 'm', itemId: 'a', requestId: 'r' })
    await flush()
    expect(bridge.call.mock.calls.at(-1)?.[0]).toBe('menuItems') // 'menus' is listed
    finishMenu({ ok: false, error: 'cancelled' })
    await shown
    removeBridge()

    const none = install({ features: [] })
    w().onNativeMenuExpand?.({ menuId: 'm', itemId: 'a', requestId: 'r' })
    w().onNativeBackRequested?.({ source: 'button' })
    await flush()
    expect(none.call).not.toHaveBeenCalled()
  })

  it('backResult is not sent for an app without backInterception', async () => {
    const bridge = install({ features: ['backInterception'] })
    const off = onBackRequested(() => true)
    removeBridge()
    const second = install({ features: [] })
    w().onNativeBackRequested?.({ source: 'button' })
    await flush()
    expect(second.call).not.toHaveBeenCalled()
    off()
    expect(bridge.call).toHaveBeenCalled() // the first app saw setBackInterception
  })

  it('page search answers are gated by pageSearch', async () => {
    let finish!: (v: unknown) => void
    const bridge = install({
      features: ['liveSurfaces', 'pageSearch'],
      call: vi.fn(async (action: string) =>
        action === 'showForm' ? new Promise((r) => (finish = r)) : { ok: true }
      ),
    })
    const shown = showForm(
      { id: 'f', fields: [{ id: 'c', type: 'search', source: 'page' }] },
      { onSearch: () => [{ value: 'a', label: 'A' }] }
    )
    // The app takes the feature away (cannot happen in practice): the answer is not forwarded.
    ;(window.BMSNative as { features?: string[] }).features = []
    w().onNativeSurfaceSearch?.({ id: 'f', fieldId: 'c', query: 'q', requestId: 'r' })
    await flush()
    expect(bridge.call.mock.calls.map(([a]) => a)).toEqual(['showForm'])
    finish({ ok: false, error: 'cancelled' })
    await shown
  })
})

// --- D9, D11, D12, D13: verified --------------------------------------------------------------------

describe('D9: the last handler removes window.onNativeDocumentsReceived', () => {
  it('deletes the function (and restores one the page had set)', async () => {
    const { onDocumentsReceived } = await import('../src/index.js')
    install({ call: answer({ ok: true, documents: [] }) })
    const off = onDocumentsReceived(() => {})
    expect(typeof w().onNativeDocumentsReceived).toBe('function')
    off()
    expect('onNativeDocumentsReceived' in window).toBe(false)
  })
})

describe('D11: back interception', () => {
  it('enables on the first handler, disables on the last, answers within 700 ms', async () => {
    vi.useFakeTimers()
    const bridge = install()
    const offA = onBackRequested(() => new Promise<boolean>(() => {}))
    const offB = onBackRequested(() => new Promise<boolean>(() => {}))
    expect(bridge.call.mock.calls.filter(([a]) => a === 'setBackInterception')).toEqual([
      ['setBackInterception', { enabled: true }],
    ])
    w().onNativeBackRequested?.({ source: 'swipe' })
    await vi.advanceTimersByTimeAsync(700)
    expect(bridge.call.mock.calls.at(-1)).toEqual(['backResult', { handled: false }])
    offA()
    offB()
    expect(bridge.call.mock.calls.at(-1)).toEqual(['setBackInterception', { enabled: false }])
  })
})

describe('D12: absolute URLs', () => {
  it('previewFile and showDocument send absolute URLs for relative and absolute input', async () => {
    const bridge = install()
    await previewFile({ url: 'files/a.pdf' })
    await showDocument({ url: '/b.pdf' })
    const origin = window.location.origin
    expect((bridge.call.mock.calls[0]?.[1] as { url: string }).url).toMatch(
      new RegExp(`^${origin}/`)
    )
    expect(bridge.call.mock.calls[1]?.[1]).toEqual({ url: `${origin}/b.pdf` })
  })
})

describe('D13: resource tokens', () => {
  it('sends refresh with resource, drops interactive without it and echoes resource', async () => {
    const bridge = install({
      call: answer({ ok: true, token: 't', expiresAt: 1, resource: 'api://x/.default' }),
    })
    const res = await getAccessToken({ resource: 'api://x/.default', refresh: true })
    expect(bridge.call).toHaveBeenCalledWith('getAccessToken', {
      refresh: true,
      resource: 'api://x/.default',
    })
    expect(res).toMatchObject({ ok: true, resource: 'api://x/.default' })
    await getAccessToken({ interactive: true })
    expect(bridge.call).toHaveBeenLastCalledWith('getAccessToken', {})
  })
})

// --- D15: menu ids and counting ---------------------------------------------------------------------

describe('D15: showMenu', () => {
  const lazy: NativeMenuSection[] = [
    {
      items: [
        { id: 'open', label: 'Open' },
        { id: 'send', label: 'Send', children: 'lazy' },
      ],
    },
  ]

  function openMenu(
    loadChildren: (id: string) => NativeMenuSection[] | Promise<NativeMenuSection[]>,
    id?: string
  ) {
    let finish!: (v: unknown) => void
    const bridge = install({
      call: vi.fn(async (action: string) =>
        action === 'showMenu' ? new Promise((r) => (finish = r)) : { ok: true }
      ),
    })
    const result = showMenu({ ...(id && { id }), anchor: ANCHOR, sections: lazy, loadChildren })
    const sentId = (bridge.call.mock.calls[0]?.[1] as { id: string }).id
    const expand = async (requestId: string, itemId = 'send') => {
      w().onNativeMenuExpand?.({ menuId: sentId, itemId, requestId })
      await flush()
    }
    return {
      bridge,
      expand,
      close: async () => (finish({ ok: false, error: 'cancelled' }), result),
      sentId,
    }
  }

  it('the package generates the menu id when loadChildren is used, and keeps a given one', async () => {
    const a = openMenu(() => [])
    expect(typeof a.sentId).toBe('string')
    expect(a.sentId.length).toBeGreaterThan(0)
    await a.close()
    removeBridge()
    const b = openMenu(() => [], 'mine')
    expect(b.sentId).toBe('mine')
    await b.close()
  })

  it('a refused answer leaves no trace: the retry with the same ids is answered', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const answers: NativeMenuSection[][] = [
      [
        {
          items: [
            { id: 'x', label: 'X' },
            { id: 'open', label: 'duplicate of the menu' },
          ],
        },
      ],
      [{ items: [{ id: 'x', label: 'X' }] }],
    ]
    const { bridge, expand, close } = openMenu(() => answers.shift()!)
    await expand('r1')
    expect(bridge.call.mock.calls.map(([a]) => a)).toEqual(['showMenu'])
    await expand('r2')
    expect(bridge.call.mock.calls.at(-1)).toEqual([
      'menuItems',
      { requestId: 'r2', sections: [{ items: [{ id: 'x', label: 'X' }] }] },
    ])
    await close()
  })

  it('asked again for the same item, the new answer replaces the old one (ids and count)', async () => {
    const big = (prefix: string, n: number): NativeMenuSection[] => [
      { items: Array.from({ length: n }, (_, k) => ({ id: `${prefix}${k}`, label: 'x' })) },
    ]
    const answers = [big('a', 70), big('a', 70), big('b', 78)]
    const { bridge, expand, close } = openMenu(() => answers.shift()!)
    await expand('r1') // 2 + 70
    await expand('r2') // replaces the first answer: same ids are fine
    await expand('r3') // 2 + 78 = 80, the limit
    expect(bridge.call.mock.calls.filter(([a]) => a === 'menuItems')).toHaveLength(3)
    await close()
  })

  it('counts the items the menu already has', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { bridge, expand, close } = openMenu(() => [
      { items: Array.from({ length: 79 }, (_, k) => ({ id: `n${k}`, label: 'x' })) },
    ])
    await expand('r1') // 2 + 79 = 81
    expect(bridge.call.mock.calls.map(([a]) => a)).toEqual(['showMenu'])
    await close()
  })

  it('an empty menu, an empty section and an empty answer are invalid', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = install()
    expect(await showMenu({ anchor: ANCHOR, sections: [] })).toMatchObject({ error: 'invalid' })
    expect(await showMenu({ anchor: ANCHOR, sections: [{ items: [] }] })).toMatchObject({
      error: 'invalid',
    })
    expect(
      await showMenu({
        anchor: ANCHOR,
        sections: [{ items: [{ id: 'a', label: 'A', children: [] }] }],
      })
    ).toMatchObject({ error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
    const empty = openMenu(() => [])
    await empty.expand('r')
    expect(empty.bridge.call.mock.calls.map(([a]) => a)).toEqual(['showMenu'])
    await empty.close()
  })
})

// --- D16, D20, D21, D7, D6, D18 -----------------------------------------------------------------------

describe('D16: alerts', () => {
  it('duplicate action ids are invalid', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = install()
    const res = await showAlert({
      title: 'T',
      actions: [
        { id: 'a', label: 'A' },
        { id: 'a', label: 'B' },
      ],
    })
    expect(res).toMatchObject({ ok: false, error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('text is always there with a textField, empty if the app left it out', async () => {
    install({ call: answer({ ok: true, id: 'ok' }) })
    expect(
      await showAlert({ title: 'T', actions: [{ id: 'ok', label: 'OK' }], textField: {} })
    ).toEqual({
      ok: true,
      id: 'ok',
      text: '',
    })
    expect(await showAlert({ title: 'T', actions: [{ id: 'ok', label: 'OK' }] })).toEqual({
      ok: true,
      id: 'ok',
    })
  })
})

describe('D20: pickers', () => {
  it('min after max is invalid, min equal to max is fine', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = install({ call: answer({ ok: true, value: '2026-11-11' }) })
    expect(await showPicker({ kind: 'date', min: '2026-12-01', max: '2026-11-01' })).toMatchObject({
      error: 'invalid',
    })
    expect(bridge.call).not.toHaveBeenCalled()
    expect((await showPicker({ kind: 'date', min: '2026-11-11', max: '2026-11-11' })).ok).toBe(true)
  })
})

describe('D21, D7, D6', () => {
  it('a document is at most 25,000,000 bytes', () => {
    expect(DOCUMENT_LIMITS.bytes).toBe(25_000_000)
  })

  it('accept takes wildcards and unknown entries are passed on', async () => {
    const bridge = install({
      call: answer({
        ok: true,
        documents: [{ name: 'a', mime: 'image/jpeg', size: 1, uploadId: 'u' }],
      }),
    })
    await pickFiles({ sources: ['photos'], accept: ['image/*', '.eml', 'whatever'] })
    expect(bridge.call).toHaveBeenCalledWith('pickFiles', {
      sources: ['photos'],
      accept: ['image/*', '.eml', 'whatever'],
    })
  })

  it('upload.body is whatever the backend sent: JSON parsed, otherwise the raw string', async () => {
    const docs = [
      {
        name: 'a',
        mime: 'x',
        size: 1,
        uploadId: 'u1',
        upload: { status: 200, body: { ok: true } },
      },
      {
        name: 'b',
        mime: 'x',
        size: 1,
        uploadId: 'u2',
        upload: { status: 200, body: '<html>ok</html>' },
      },
      {
        name: 'c',
        uploadId: 'u3',
        error: 'failed',
        upload: { status: 503, body: { detail: 'Try again' } },
      },
      { name: 'd', uploadId: 'u4', error: 'failed' },
    ]
    install({ call: answer({ ok: true, documents: docs }) })
    const res = await pickFiles({ sources: ['files'] })
    expect(res).toEqual({ ok: true, documents: docs })
  })
})

describe('D18: sidebar', () => {
  const item = (id: string, extra = {}) => ({ id, label: id, ...extra })
  const action = (id: string) => ({ id, label: id })

  it('at most 3 swipe actions and at most one selected item', () => {
    expect(CHROME_LIMITS.sidebarActions).toBe(3)
    const fine = {
      title: 'T',
      sections: [
        {
          items: [
            item('a', { selected: true, trailingActions: [action('x'), action('y'), action('z')] }),
          ],
        },
      ],
    }
    expect(chromeLimitWarnings({ sidebar: fine })).toEqual([])
    const four = {
      title: 'T',
      sections: [
        {
          items: [
            item('a', { trailingActions: [action('1'), action('2'), action('3'), action('4')] }),
          ],
        },
      ],
    }
    expect(chromeLimitWarnings({ sidebar: four })[0]).toContain('4 swipe actions')
    const two = {
      title: 'T',
      sections: [{ items: [item('a', { selected: true }), item('b', { selected: true })] }],
    }
    expect(chromeLimitWarnings({ sidebar: two })[0]).toContain('2 selected items')
  })
})
