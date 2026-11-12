import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import {
  ALERT_LIMITS,
  CHROME_LIMITS,
  FEATURES,
  KEYBOARD_LIMITS,
  MENU_LIMITS,
  anchorOf,
  chromeLimitWarnings,
  hasFeature,
  menuLimitWarnings,
  on,
  setChrome,
  setKeyCommands,
  setKeyboardToolbar,
  showAlert,
  showMenu,
  showPicker,
  toast,
  type NativeMenuSection,
} from '../src/index.js'
import { installBridge as installUntyped, removeBridge } from './helpers.js'

afterEach(() => {
  vi.useRealTimers()
  removeBridge()
})

const ALL = [...FEATURES]
const ANCHOR = { x: 24, y: 120, width: 44, height: 44 }

function installBridge(overrides: Parameters<typeof installUntyped>[0] = {}) {
  return installUntyped({ features: ALL, ...overrides }) as unknown as {
    call: Mock
    postMessage: Mock
  }
}

function answer(result: unknown) {
  return vi.fn(async (_action: string, _payload?: Record<string, unknown>) => result)
}

const flush = async () => {
  for (let i = 0; i < 8; i++) await Promise.resolve()
}

const items = (n: number): NativeMenuSection[] => [
  { items: Array.from({ length: n }, (_, k) => ({ id: `i${k}`, label: `Item ${k}` })) },
]

describe('FEATURES', () => {
  it('lists every flag of the contract, 2026-11 and 2026-11b', () => {
    expect([...FEATURES].sort()).toEqual(
      [
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
        'menus',
        'titleMenu',
        'alerts',
        'toastActions',
        'liveSurfaces',
        'pageSearch',
        'navSearch',
        'keyboardToolbar',
        'segments',
        'sidebar',
        'documentViewer',
        'undoGestures',
        'pickers',
        'keyCommands',
      ].sort()
    )
  })

  it('hasFeature covers the new flags', () => {
    installBridge({ features: ['menus', 'pickers'] })
    expect(hasFeature('menus')).toBe(true)
    expect(hasFeature('alerts')).toBe(false)
  })
})

describe('menuLimitWarnings', () => {
  it('accepts the limits exactly', () => {
    expect(menuLimitWarnings(items(MENU_LIMITS.items))).toEqual([])
    expect(
      menuLimitWarnings([{ items: [{ id: 'a', label: 'x'.repeat(MENU_LIMITS.label) }] }])
    ).toEqual([])
  })

  it('counts items of all levels together', () => {
    const nested: NativeMenuSection[] = [
      { items: [{ id: 'root', label: 'r', children: items(MENU_LIMITS.items) }] },
    ]
    expect(menuLimitWarnings(nested)[0]).toContain('81 items')
  })

  it('allows two levels of submenus and not a third', () => {
    const level = (children?: NativeMenuSection[]): NativeMenuSection[] => [
      { items: [{ id: `n${Math.random()}`, label: 'n', ...(children && { children }) }] },
    ]
    expect(menuLimitWarnings(level(level(level())))).toEqual([])
    expect(menuLimitWarnings(level(level(level(level()))))[0]).toContain('nested too deep')
  })

  it('counts characters, not UTF-16 units', () => {
    expect(menuLimitWarnings([{ items: [{ id: 'a', label: '😀'.repeat(80) }] }])).toEqual([])
    expect(menuLimitWarnings([{ items: [{ id: 'a', label: '😀'.repeat(81) }] }])).not.toEqual([])
  })

  it('finds duplicate ids at any level, missing ids and bad children', () => {
    expect(
      menuLimitWarnings([
        {
          items: [
            { id: 'a', label: 'A', children: items(1) },
            { id: 'a', label: 'B' },
          ],
        },
      ])[0]
    ).toContain('twice')
    expect(menuLimitWarnings([{ items: [{ label: 'A' } as never] }])[0]).toContain('id')
    expect(
      menuLimitWarnings([{ items: [{ id: 'a', label: 'A', children: 'eager' as never }] }])[0]
    ).toContain('has to be a list')
  })
})

describe('showMenu', () => {
  const sections: NativeMenuSection[] = [{ items: [{ id: 'open', label: 'Open' }] }]

  it('sends the menu and resolves the chosen id', async () => {
    const bridge = installBridge({ call: answer({ ok: true, id: 'open' }) })
    const preview = { title: 'Offer 4711', subtitle: 'Müller AG' }
    expect(await showMenu({ anchor: ANCHOR, preview, sections })).toEqual({ ok: true, id: 'open' })
    expect(bridge.call).toHaveBeenCalledWith('showMenu', { anchor: ANCHOR, preview, sections })
  })

  it.each(['cancelled', 'busy', 'capability'])('passes %s through', async (error) => {
    installBridge({ call: answer({ ok: false, error }) })
    expect(await showMenu({ anchor: ANCHOR, sections })).toEqual({ ok: false, error })
  })

  it('answers invalid without asking the app, and warns in development', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge()
    expect(await showMenu({ anchor: ANCHOR, sections: items(81) })).toMatchObject({
      ok: false,
      error: 'invalid',
    })
    expect(await showMenu({ anchor: { x: 1 } as never, sections })).toMatchObject({
      error: 'invalid',
    })
    expect(bridge.call).not.toHaveBeenCalled()
    expect(warn).toHaveBeenCalledTimes(2)
  })

  it('is unavailable outside the app, in an old app and for unknownAction', async () => {
    expect(await showMenu({ anchor: ANCHOR, sections })).toEqual({
      ok: false,
      error: 'unavailable',
    })
    const bridge = installBridge({ features: [] })
    expect(await showMenu({ anchor: ANCHOR, sections })).toEqual({
      ok: false,
      error: 'unavailable',
    })
    expect(bridge.call).not.toHaveBeenCalled()
    removeBridge()
    installBridge({ call: answer({ ok: false, error: 'unknownAction' }) })
    expect(await showMenu({ anchor: ANCHOR, sections })).toEqual({
      ok: false,
      error: 'unknownAction',
    })
  })

  describe('lazy children', () => {
    const lazy: NativeMenuSection[] = [
      {
        items: [
          { id: 'open', label: 'Open' },
          { id: 'send', label: 'Send to …', children: 'lazy' },
        ],
      },
    ]

    function openMenu(
      loadChildren: (id: string) => NativeMenuSection[] | Promise<NativeMenuSection[]>
    ) {
      let finish!: (value: unknown) => void
      const shown = new Promise((resolve) => (finish = resolve))
      const bridge = installBridge({
        call: vi.fn(async (action: string) => (action === 'showMenu' ? shown : { ok: true })),
      })
      const result = showMenu({ id: 'm1', anchor: ANCHOR, sections: lazy, loadChildren })
      const expand = (itemId = 'send', requestId = 'r1') =>
        (window as unknown as { onNativeMenuExpand: (e: unknown) => void }).onNativeMenuExpand({
          menuId: 'm1',
          itemId,
          requestId,
        })
      return { bridge, result, expand, finish }
    }

    it('answers the expand event with menuItems and drops loadChildren from the payload', async () => {
      const loadChildren = vi.fn(async () => items(2))
      const { bridge, result, expand, finish } = openMenu(loadChildren)
      expect(bridge.call.mock.calls[0]).toEqual([
        'showMenu',
        { id: 'm1', anchor: ANCHOR, sections: lazy },
      ])
      expand()
      await flush()
      expect(loadChildren).toHaveBeenCalledWith('send')
      expect(bridge.call).toHaveBeenLastCalledWith('menuItems', {
        requestId: 'r1',
        sections: items(2),
      })
      finish({ ok: true, id: 'i0' })
      expect(await result).toEqual({ ok: true, id: 'i0' })
    })

    it('generates an id when loadChildren is given without one', async () => {
      const bridge = installBridge({ call: answer({ ok: true, id: 'open' }) })
      await showMenu({ anchor: ANCHOR, sections: lazy, loadChildren: () => [] })
      const payload = bridge.call.mock.calls[0]?.[1] as { id?: string }
      expect(typeof payload.id).toBe('string')
    })

    it('does not answer when loadChildren rejects or returns an invalid menu', async () => {
      vi.spyOn(console, 'warn').mockImplementation(() => {})
      const { bridge, result, expand, finish } = openMenu(async () => {
        throw new Error('offline')
      })
      expand()
      await flush()
      expect(bridge.call).toHaveBeenCalledTimes(1)
      finish({ ok: false, error: 'cancelled' })
      await result
      removeBridge()

      const second = openMenu(() => [{ items: [{ id: 'open', label: 'duplicate of the menu' }] }])
      second.expand()
      await flush()
      expect(second.bridge.call).toHaveBeenCalledTimes(1)
      second.finish({ ok: false, error: 'cancelled' })
      await second.result
    })

    it('checks the depth of the lazy item and the budget of items', async () => {
      vi.spyOn(console, 'warn').mockImplementation(() => {})
      const deep = openMenu(() => [
        {
          items: [
            {
              id: 'a',
              label: 'a',
              children: [
                {
                  items: [
                    { id: 'b', label: 'b', children: [{ items: [{ id: 'c', label: 'c' }] }] },
                  ],
                },
              ],
            },
          ],
        },
      ])
      deep.expand()
      await flush()
      expect(deep.bridge.call).toHaveBeenCalledTimes(1) // a is level 1, b level 2, c level 3
      deep.finish({ ok: false, error: 'cancelled' })
      await deep.result
      removeBridge()
      const big = openMenu(() =>
        items(MENU_LIMITS.items).map((s) => ({
          items: s.items.map((i) => ({ ...i, id: `n${i.id}` })),
        }))
      )
      big.expand()
      await flush()
      expect(big.bridge.call).toHaveBeenCalledTimes(1) // 2 + 80 items
      big.finish({ ok: false, error: 'cancelled' })
      await big.result
    })

    it('ignores expand events of other menus and after the menu closed', async () => {
      const loadChildren = vi.fn(async () => items(1))
      const { result, finish } = openMenu(loadChildren)
      ;(window as unknown as { onNativeMenuExpand: (e: unknown) => void }).onNativeMenuExpand({
        menuId: 'other',
        itemId: 'send',
        requestId: 'r',
      })
      finish({ ok: false, error: 'cancelled' })
      await result
      ;(window as unknown as { onNativeMenuExpand: (e: unknown) => void }).onNativeMenuExpand({
        menuId: 'm1',
        itemId: 'send',
        requestId: 'r',
      })
      await flush()
      expect(loadChildren).not.toHaveBeenCalled()
    })

    it('reports a second menu with the same id as busy', async () => {
      const { result, finish } = openMenu(() => [])
      const second = await showMenu({
        id: 'm1',
        anchor: ANCHOR,
        sections: lazy,
        loadChildren: () => [],
      })
      expect(second).toMatchObject({ ok: false, error: 'busy' })
      finish({ ok: false, error: 'cancelled' })
      await result
    })
  })

  it('anchorOf reads the rectangle of an element', () => {
    const element = document.createElement('div')
    element.getBoundingClientRect = () => ({ x: 1, y: 2, width: 3, height: 4 }) as DOMRect
    expect(anchorOf(element)).toEqual({ x: 1, y: 2, width: 3, height: 4 })
  })
})

describe('showAlert', () => {
  const cancel = { id: 'cancel', label: 'Cancel', style: 'cancel' as const }

  it('sends the alert and returns the id and the text', async () => {
    const bridge = installBridge({ call: answer({ ok: true, id: 'ok', text: 'Offer 4712' }) })
    const options = {
      title: 'Rename',
      actions: [cancel, { id: 'ok', label: 'OK', preferred: true }],
      textField: { value: 'Offer 4711', maxLength: 40 },
    }
    expect(await showAlert(options)).toEqual({ ok: true, id: 'ok', text: 'Offer 4712' })
    expect(bridge.call).toHaveBeenCalledWith('showAlert', options)
  })

  it('omits text without a text field', async () => {
    installBridge({ call: answer({ ok: true, id: 'ok' }) })
    expect(await showAlert({ title: 'T', actions: [cancel] })).toEqual({ ok: true, id: 'ok' })
  })

  it.each([
    ['no actions', { title: 'T', actions: [] }],
    [
      'too many actions',
      {
        title: 'T',
        actions: Array.from({ length: ALERT_LIMITS.actions + 1 }, (_, k) => ({
          id: `a${k}`,
          label: 'x',
        })),
      },
    ],
    ['two cancels', { title: 'T', actions: [cancel, { ...cancel, id: 'c2' }] }],
    [
      'a text field in an action sheet',
      { title: 'T', style: 'actionSheet', actions: [cancel], textField: {} },
    ],
    ['an unknown keyboard', { title: 'T', actions: [cancel], textField: { keyboard: 'phone' } }],
    ['no title', { actions: [cancel] }],
  ])('answers invalid without asking the app: %s', async (_name, options) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge()
    expect(await showAlert(options as never)).toMatchObject({ ok: false, error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('never falls back to window.confirm or prompt', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('x')
    expect(await showAlert({ title: 'T', actions: [cancel] })).toEqual({
      ok: false,
      error: 'unavailable',
    })
    installBridge({ features: [] })
    expect(await showAlert({ title: 'T', actions: [cancel] })).toEqual({
      ok: false,
      error: 'unavailable',
    })
    expect(confirm).not.toHaveBeenCalled()
    expect(prompt).not.toHaveBeenCalled()
  })

  it('passes cancelled through and treats unknownAction as unavailable', async () => {
    installBridge({ call: answer({ ok: false, error: 'cancelled' }) })
    expect(await showAlert({ title: 'T', actions: [{ id: 'a', label: 'A' }] })).toEqual({
      ok: false,
      error: 'cancelled',
    })
    removeBridge()
    installBridge({ call: answer({ ok: false, error: 'unknownAction' }) })
    expect(await showAlert({ title: 'T', actions: [cancel] })).toEqual({
      ok: false,
      error: 'unknownAction',
    })
  })
})

describe('showPicker', () => {
  it('sends a date picker and returns the value', async () => {
    const bridge = installBridge({ call: answer({ ok: true, value: '2026-12-01' }) })
    const options = {
      kind: 'date' as const,
      title: 'Valid until',
      value: '2026-11-30',
      min: '2026-11-11',
    }
    expect(await showPicker(options)).toEqual({ ok: true, value: '2026-12-01' })
    expect(bridge.call).toHaveBeenCalledWith('showPicker', options)
  })

  it.each([
    ['a date in the wrong format', { kind: 'date', value: '30.11.2026' }],
    ['a date that does not exist', { kind: 'date', max: '2026-02-30' }],
    ['no options', { kind: 'option' }],
    [
      '201 options',
      {
        kind: 'option',
        options: Array.from({ length: 201 }, (_, k) => ({ value: `${k}`, label: 'x' })),
      },
    ],
    ['an unknown kind', { kind: 'time' }],
  ])('answers invalid without asking the app: %s', async (_name, options) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge()
    expect(await showPicker(options as never)).toMatchObject({ error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('has no browser fallback', async () => {
    expect(await showPicker({ kind: 'date' })).toEqual({ ok: false, error: 'unavailable' })
    installBridge({ features: [] })
    expect(await showPicker({ kind: 'date' })).toEqual({ ok: false, error: 'unavailable' })
  })
})

describe('toast with an action', () => {
  const tap = (event: unknown) =>
    (window as unknown as { onNativeToastAction: (e: unknown) => void }).onNativeToastAction(event)

  it('returns the toastId and calls onAction once on a tap', async () => {
    const bridge = installBridge({ call: answer({ ok: true, toastId: 't-1' }) })
    const onAction = vi.fn()
    const res = await toast('Deleted', {
      action: { id: 'undo', label: 'Undo' },
      onAction,
      duration: 4,
    })
    expect(res).toEqual({ ok: true, toastId: 't-1' })
    expect(bridge.call).toHaveBeenCalledWith('toast', {
      message: 'Deleted',
      action: { id: 'undo', label: 'Undo' },
      duration: 4,
    })
    tap({ toastId: 'other', id: 'undo' })
    expect(onAction).not.toHaveBeenCalled()
    tap({ toastId: 't-1', id: 'undo' })
    tap({ toastId: 't-1', id: 'undo' }) // the toast closed with the first tap
    expect(onAction).toHaveBeenCalledOnce()
    expect(onAction).toHaveBeenCalledWith('undo')
  })

  it('drops the handler of a toast that a new toast replaced', async () => {
    let n = 0
    installBridge({ call: vi.fn(async () => ({ ok: true, toastId: `t-${++n}` })) })
    const first = vi.fn()
    const second = vi.fn()
    await toast('One', { action: { id: 'a', label: 'A' }, onAction: first })
    await toast('Two', { action: { id: 'b', label: 'B' }, onAction: second })
    tap({ toastId: 't-1', id: 'a' })
    tap({ toastId: 't-2', id: 'b' })
    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledWith('b')
    await toast('Three', { duration: 2 }) // replaced by a toast without action
    tap({ toastId: 't-2', id: 'b' })
    expect(second).toHaveBeenCalledOnce()
  })

  it.each([
    ['duration 0.5', { duration: 0.5 }],
    ['duration 11', { duration: 11 }],
    ['an action without label', { action: { id: 'a' } }],
    ['an unknown style', { style: 'loud' }],
  ])('answers invalid without asking the app: %s', async (_name, options) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge()
    expect(await toast('x', options as never)).toMatchObject({ ok: false, error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('is unavailable outside the app and without the feature', async () => {
    expect(await toast('x', { duration: 2 })).toEqual({ ok: false, error: 'unavailable' })
    const bridge = installBridge({ features: [] })
    expect(await toast('x', { duration: 2 })).toEqual({ ok: false, error: 'unavailable' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('leaves the fire-and-forget form as it was', () => {
    const bridge = installBridge()
    toast('Saved', 'success', 3)
    toast('Plain')
    expect(bridge.postMessage).toHaveBeenNthCalledWith(1, {
      action: 'toast',
      message: 'Saved',
      style: 'success',
      duration: 3,
    })
    expect(bridge.postMessage).toHaveBeenNthCalledWith(2, {
      action: 'toast',
      message: 'Plain',
      style: 'info',
    })
    expect(bridge.call).not.toHaveBeenCalled()
  })
})

describe('setChrome additions', () => {
  const search = { id: 'offers', placeholder: 'Search' }

  it('sends them as they are and warns about nothing valid', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge({ capabilities: ['customChrome', 'camera'] })
    const chrome = {
      title: { text: 'Offer 4711', subtitle: 'Müller AG', menu: items(2) },
      search: { ...search, scopes: [{ id: 'all', label: 'All' }], scope: 'all', barcode: true },
      segments: {
        id: 'v',
        items: [
          { id: 'a', label: 'A' },
          { id: 'b', label: 'B', badge: '3' },
        ],
        selected: 'a',
      },
      sidebar: { title: 'Offers', sections: [{ items: [{ id: 'o1', label: 'Offer' }] }] },
      undo: { canUndo: true, canRedo: false, undoLabel: 'Delete' },
      actionButtons: [{ id: 'more', icon: 'ellipsis', menu: items(2) }],
    }
    setChrome(chrome)
    expect(bridge.postMessage).toHaveBeenCalledWith({ ...chrome, action: 'setChrome' })
    expect(warn).not.toHaveBeenCalled()
  })

  it('does nothing outside the app', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    setChrome({ search, undo: { canUndo: true, canRedo: true } })
    expect(warn).not.toHaveBeenCalled()
  })

  it('warns in development builds about what the app lacks and about limits, and leaves it out', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge({ features: ['menus'] })
    setChrome({ search, segments: { id: 'v', items: [{ id: 'a', label: 'A' }], selected: 'a' } })
    // Both parts need features that this app does not list: nothing is left to send.
    expect(bridge.postMessage).not.toHaveBeenCalled()
    const text = warn.mock.calls.map((c) => String(c[0])).join('\n')
    expect(text).toContain('navSearch')
    expect(text).toContain('segments has 1 items')
  })

  it('does not warn in a production bundle', () => {
    vi.stubEnv('NODE_ENV', 'production')
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    installBridge({ features: [] })
    setChrome({ search: { id: '' } as never })
    expect(warn).not.toHaveBeenCalled()
  })

  it('chromeLimitWarnings checks every part', () => {
    expect(chromeLimitWarnings({ title: {} as never })[0]).toContain('title.text')
    expect(chromeLimitWarnings({ search: { id: 'o', placeholder: 'p', scope: 'x' } })[0]).toContain(
      'no scopes'
    )
    expect(
      chromeLimitWarnings({
        segments: {
          id: 'v',
          items: Array.from({ length: CHROME_LIMITS.segments.max + 1 }, (_, k) => ({
            id: `s${k}`,
            label: 'x',
          })),
          selected: 's0',
        },
      })[0]
    ).toContain('2 to 5')
    expect(
      chromeLimitWarnings({
        sidebar: {
          title: 'T',
          sections: [
            {
              items: Array.from({ length: CHROME_LIMITS.sidebarItems + 1 }, (_, k) => ({
                id: `o${k}`,
                label: 'x',
              })),
            },
          ],
        },
      })[0]
    ).toContain('301 items')
    expect(chromeLimitWarnings({ undo: { canUndo: 'yes' } as never })[0]).toContain('undo.canUndo')
    expect(
      chromeLimitWarnings({ actionButtons: [{ id: 'a', icon: 'i', menu: items(81) }] })[0]
    ).toContain('actionButtons[0].menu')
  })

  it('warns about lazy items in the menus of the bar, which have no menuId to answer', () => {
    const lazy: NativeMenuSection[] = [{ items: [{ id: 'a', label: 'A', children: 'lazy' }] }]
    expect(chromeLimitWarnings({ title: { text: 'T', menu: lazy } })[0]).toContain('showMenu')
    expect(
      chromeLimitWarnings({ actionButtons: [{ id: 'b', icon: 'i', menu: lazy }] })[0]
    ).toContain('showMenu')
  })

  it('delivers the events of the additions', () => {
    const seen: unknown[] = []
    const w = window as unknown as Record<string, (e: unknown) => void>
    const offs = [
      on('actionButtonMenuSelect', (e) => seen.push(['button', e])),
      on('titleMenuSelect', (e) => seen.push(['title', e])),
      on('search', (e) => seen.push(['search', e])),
      on('searchCancel', (e) => seen.push(['cancel', e])),
      on('segmentSelect', (e) => seen.push(['segment', e])),
      on('sidebarSelect', (e) => seen.push(['side', e])),
      on('sidebarAction', (e) => seen.push(['sideAction', e])),
      on('sidebarSearch', (e) => seen.push(['sideSearch', e])),
      on('undo', (e) => seen.push(['undo', e])),
      on('keyCommand', (e) => seen.push(['key', e])),
      on('keyboardToolbarTap', (e) => seen.push(['toolbar', e])),
    ]
    w.onNativeActionButtonMenuSelect?.({ buttonId: 'b', id: 'i' })
    w.onNativeTitleMenuSelect?.({ id: 't' })
    w.onNativeSearch?.({ id: 's', query: 'q', scope: null, submitted: false, source: 'typing' })
    w.onNativeSearchCancel?.({ id: 's' })
    w.onNativeSegmentSelect?.({ id: 'v', item: 'a' })
    w.onNativeSidebarSelect?.({ id: 'o1' })
    w.onNativeSidebarAction?.({ itemId: 'o1', id: 'del' })
    w.onNativeSidebarSearch?.({ query: 'q' })
    w.onNativeUndo?.({ action: 'redo' })
    w.onNativeKeyCommand?.({ id: 'k' })
    w.onNativeKeyboardToolbarTap?.({ id: 'add' })
    expect(seen.map((s) => (s as unknown[])[0])).toEqual([
      'button',
      'title',
      'search',
      'cancel',
      'segment',
      'side',
      'sideAction',
      'sideSearch',
      'undo',
      'key',
      'toolbar',
    ])
    offs.forEach((off) => off())
  })
})

describe('setKeyboardToolbar', () => {
  it('sends the toolbar', async () => {
    const bridge = installBridge()
    const options = {
      items: [
        { id: 'prev', icon: 'chevron.up' },
        { id: 'add', label: 'Add', style: 'prominent' as const },
      ],
      done: true,
    }
    expect(await setKeyboardToolbar(options)).toEqual({ ok: true })
    expect(bridge.call).toHaveBeenCalledWith('setKeyboardToolbar', options)
    await setKeyboardToolbar({ items: [] })
    expect(bridge.call).toHaveBeenLastCalledWith('setKeyboardToolbar', { items: [] })
  })

  it.each([
    [
      '7 items',
      {
        items: Array.from({ length: KEYBOARD_LIMITS.toolbarItems + 1 }, (_, k) => ({
          id: `t${k}`,
          label: 'x',
        })),
      },
    ],
    ['no label and no icon', { items: [{ id: 'x' }] }],
    ['an unknown style', { items: [{ id: 'x', label: 'x', style: 'loud' }] }],
  ])('answers invalid without asking the app: %s', async (_name, options) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge()
    expect(await setKeyboardToolbar(options as never)).toMatchObject({ error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('is unavailable in the browser and without the feature, and passes capability', async () => {
    expect(await setKeyboardToolbar({ items: [] })).toEqual({ ok: false, error: 'unavailable' })
    installBridge({ call: answer({ ok: false, error: 'capability' }) })
    expect(await setKeyboardToolbar({ items: [] })).toEqual({ ok: false, error: 'capability' })
  })
})

describe('setKeyCommands', () => {
  const command = {
    id: 'search',
    input: 'k',
    modifiers: ['command' as const],
    title: 'Search',
    group: 'Offers',
  }

  it('sends the commands', async () => {
    const bridge = installBridge()
    expect(
      await setKeyCommands({
        commands: [command, { id: 'next', input: 'down', modifiers: [], title: 'Next' }],
      })
    ).toEqual({ ok: true })
    expect(bridge.call).toHaveBeenCalledOnce()
    await setKeyCommands({ commands: [] })
    expect(bridge.call).toHaveBeenLastCalledWith('setKeyCommands', { commands: [] })
  })

  it.each([
    [
      '61 commands',
      {
        commands: Array.from({ length: KEYBOARD_LIMITS.keyCommands + 1 }, (_, k) => ({
          ...command,
          id: `c${k}`,
        })),
      },
    ],
    ['two characters', { commands: [{ ...command, input: 'ab' }] }],
    ['a key name the contract does not have', { commands: [{ ...command, input: 'enter' }] }],
    ['an unknown modifier', { commands: [{ ...command, modifiers: ['meta'] }] }],
    ['no modifiers list', { commands: [{ id: 'x', input: 'k', title: 'X' }] }],
    ['no title', { commands: [{ ...command, title: '' }] }],
  ])('answers invalid without asking the app: %s', async (_name, options) => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const bridge = installBridge()
    expect(await setKeyCommands(options as never)).toMatchObject({ error: 'invalid' })
    expect(bridge.call).not.toHaveBeenCalled()
  })

  it('accepts a character outside the BMP as one character', async () => {
    const bridge = installBridge()
    await setKeyCommands({ commands: [{ ...command, input: '😀' }] })
    expect(bridge.call).toHaveBeenCalledOnce()
  })

  it('is unavailable outside the app and for unknownAction', async () => {
    expect(await setKeyCommands({ commands: [] })).toEqual({ ok: false, error: 'unavailable' })
    installBridge({ call: answer({ ok: false, error: 'unknownAction' }) })
    expect(await setKeyCommands({ commands: [] })).toEqual({ ok: false, error: 'unknownAction' })
  })
})
