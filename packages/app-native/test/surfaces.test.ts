import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import {
  NATIVE_SURFACE_LIMITS,
  canShowNativeContent,
  canShowNativeForms,
  closeSurface,
  contentLimitWarnings,
  formLimitWarnings,
  isNativeSurfaceUnsupported,
  on,
  showContent,
  showForm,
  surfaceResult,
  type NativeContentDef,
  type NativeFormDef,
  type NativeFormField,
  type NativeFormResult,
  type NativeSurfaceActionEvent,
} from '../src/index.js'
import { installBridge as installBridgeUntyped, removeBridge } from './helpers.js'

/** The bridge of the helper, with `call` and `postMessage` typed as the mocks they are. */
function installBridge(overrides: Parameters<typeof installBridgeUntyped>[0] = {}) {
  return installBridgeUntyped(overrides) as unknown as { call: Mock; postMessage: Mock }
}

type Trigger = (event: NativeSurfaceActionEvent) => void

/** The app calling the page: `window.onNativeSurfaceAction(...)`. */
function appCallsPage(event: NativeSurfaceActionEvent): void {
  const trigger = (window as unknown as { onNativeSurfaceAction?: Trigger }).onNativeSurfaceAction
  if (!trigger) throw new Error('window.onNativeSurfaceAction is not defined')
  trigger(event)
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

/**
 * A bridge whose `showForm`/`showContent` stay pending until the test resolves
 * them (the surface is "open"); everything else answers `{ ok: true }`.
 */
function installSurfaceBridge(capabilities: string[] = ['nativeForms', 'nativeContent']) {
  const surface = deferred<unknown>()
  const bridge = installBridge({
    capabilities,
    call: vi.fn(async (action: string) =>
      action === 'showForm' || action === 'showContent' ? surface.promise : { ok: true }
    ),
  })
  return { bridge, surface }
}

const sentResults = (bridge: { call: Mock }) =>
  bridge.call.mock.calls.filter(([action]) => action === 'surfaceResult').map(([, p]) => p)

const customerForm: NativeFormDef = {
  id: 'new-customer',
  title: 'New customer',
  fields: [{ id: 'name', type: 'text', label: 'Name', required: true }],
}

afterEach(removeBridge)

describe('showForm / showContent', () => {
  it('sends the definition unchanged to the app and passes the result through', async () => {
    const result: NativeFormResult = {
      ok: true,
      id: 'new-customer',
      action: 'submit',
      values: { name: 'Miller Ltd', seats: 3, vip: true, tags: ['a'] },
      labels: { owner: 'Anna Muster' },
      context: { source: 'list' },
    }
    const bridge = installBridge({ call: vi.fn(async () => result) })
    const def: NativeFormDef = { ...customerForm, size: 'fit', context: { source: 'list' } }

    expect(await showForm(def)).toEqual(result)
    expect(bridge.call).toHaveBeenCalledWith('showForm', def)
    expect(bridge.postMessage).not.toHaveBeenCalled()
  })

  it('sends content unchanged and returns the tapped action', async () => {
    const def: NativeContentDef = {
      title: 'Miller Ltd',
      blocks: [{ type: 'text', markdown: 'Hello' }],
      actions: [{ id: 'new-order', label: 'New order' }],
    }
    const bridge = installBridge({
      call: vi.fn(async () => ({ ok: true, id: 'surface-1', action: 'new-order' })),
    })

    expect(await showContent(def)).toEqual({ ok: true, id: 'surface-1', action: 'new-order' })
    expect(bridge.call).toHaveBeenCalledWith('showContent', def)
  })

  it('passes the app errors through', async () => {
    for (const error of ['cancelled', 'busy', 'capability', 'unknownAction', 'tooLarge'] as const) {
      installBridge({ call: vi.fn(async () => ({ ok: false, error, message: 'why' })) })
      expect(await showForm(customerForm)).toEqual({ ok: false, error, message: 'why' })
      expect(await showContent({ blocks: [] })).toEqual({ ok: false, error, message: 'why' })
    }
  })

  it('is unavailable outside the app and never throws', async () => {
    expect(await showForm(customerForm)).toEqual({ ok: false, error: 'unavailable' })
    expect(await showContent({ blocks: [] })).toEqual({ ok: false, error: 'unavailable' })
    expect(await showForm(customerForm, { onSubmit: () => {} })).toEqual({
      ok: false,
      error: 'unavailable',
    })
    expect(await closeSurface()).toEqual({ ok: false, error: 'unavailable' })
    expect(await surfaceResult({ id: 'x', ok: true })).toEqual({ ok: false, error: 'unavailable' })
  })

  it('reports unavailable when the bridge call throws', async () => {
    installBridge({
      call: vi.fn(async () => {
        throw new Error('bridge gone')
      }),
    })
    expect(await showForm(customerForm)).toEqual({ ok: false, error: 'unavailable' })
  })

  it('does not install the page callback outside the app', async () => {
    const before = (window as unknown as { onNativeSurfaceAction?: unknown }).onNativeSurfaceAction
    await showForm({ ...customerForm, id: 'outside' }, { onSubmit: () => {} })
    expect((window as unknown as { onNativeSurfaceAction?: unknown }).onNativeSurfaceAction).toBe(
      before
    )
  })
})

describe('closeSurface and surfaceResult', () => {
  it('send their payload', async () => {
    const bridge = installBridge()
    expect(await closeSurface()).toEqual({ ok: true })
    await closeSurface({ id: 'new-customer' })
    await surfaceResult({
      id: 'new-customer',
      ok: false,
      message: 'Could not save.',
      fieldErrors: { email: 'Already registered' },
    })
    expect(bridge.call).toHaveBeenNthCalledWith(1, 'closeSurface', {})
    expect(bridge.call).toHaveBeenNthCalledWith(2, 'closeSurface', { id: 'new-customer' })
    expect(bridge.call).toHaveBeenNthCalledWith(3, 'surfaceResult', {
      id: 'new-customer',
      ok: false,
      message: 'Could not save.',
      fieldErrors: { email: 'Already registered' },
    })
  })
})

describe('capability and fallback helpers', () => {
  it('reads the capabilities of the web app', () => {
    installBridge({ capabilities: ['nativeForms'] })
    expect(canShowNativeForms()).toBe(true)
    expect(canShowNativeContent()).toBe(false)
    installBridge({ capabilities: ['nativeContent', 'camera'] })
    expect(canShowNativeForms()).toBe(false)
    expect(canShowNativeContent()).toBe(true)
  })

  it('is false outside the app and in an app without the list', () => {
    expect(canShowNativeForms()).toBe(false)
    expect(canShowNativeContent()).toBe(false)
    installBridge({ capabilities: undefined })
    expect(canShowNativeForms()).toBe(false)
  })

  it('is false on an old build that only has the raw message handler', () => {
    window.webkit = { messageHandlers: { nativeBridge: { postMessage: vi.fn() } } }
    expect(canShowNativeForms()).toBe(false)
  })

  it('treats unavailable, unknownAction and capability as "use the web UI"', () => {
    const failure = (error: string) => ({ ok: false, error }) as NativeFormResult
    expect(isNativeSurfaceUnsupported(failure('unavailable'))).toBe(true)
    expect(isNativeSurfaceUnsupported(failure('unknownAction'))).toBe(true)
    expect(isNativeSurfaceUnsupported(failure('capability'))).toBe(true)
    for (const error of ['cancelled', 'busy', 'invalid', 'tooLarge', 'failed', 'forbidden']) {
      expect(isNativeSurfaceUnsupported(failure(error))).toBe(false)
    }
    expect(
      isNativeSurfaceUnsupported({ ok: true, id: 'x', action: 'submit', values: {}, labels: {} })
    ).toBe(false)
  })
})

describe('round trip: showForm with onSubmit', () => {
  it('sets id and wait, hands the values to the handler and closes on success', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const onSubmit = vi.fn(async () => {})
    const def: NativeFormDef = { fields: customerForm.fields, submit: { label: 'Create' } }

    const pending = showForm(def, { onSubmit })

    const [action, payload] = bridge.call.mock.calls[0] as [string, NativeFormDef]
    expect(action).toBe('showForm')
    expect(payload.id).toEqual(expect.any(String))
    expect(payload.submit).toEqual({ label: 'Create', wait: true })
    expect(def).toEqual({ fields: customerForm.fields, submit: { label: 'Create' } }) // untouched

    appCallsPage({
      id: payload.id as string,
      action: 'submit',
      values: { name: 'Miller Ltd' },
      context: { source: 'list' },
    })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(1))

    expect(onSubmit).toHaveBeenCalledWith(
      { name: 'Miller Ltd' },
      {
        id: payload.id,
        action: 'submit',
        values: { name: 'Miller Ltd' },
        context: { source: 'list' },
      }
    )
    expect(sentResults(bridge)).toEqual([{ id: payload.id, ok: true }])

    const result = { ok: true, id: payload.id, action: 'submit', values: {}, labels: {} }
    surface.resolve(result)
    expect(await pending).toEqual(result)
  })

  it('keeps the id the page gave and adds wait to an existing submit', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const pending = showForm(
      { ...customerForm, submit: { confirm: 'Sure?', biometric: true } },
      { onSubmit: () => {} }
    )
    expect(bridge.call).toHaveBeenCalledWith('showForm', {
      ...customerForm,
      submit: { confirm: 'Sure?', biometric: true, wait: true },
    })
    surface.resolve({ ok: false, error: 'cancelled' })
    await pending
  })

  it('answers ok: false with the field errors that the handler returns', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const pending = showForm(customerForm, {
      onSubmit: async () => ({ fieldErrors: { email: 'Already registered' }, message: 'Fix it' }),
    })

    appCallsPage({ id: 'new-customer', action: 'submit', values: { email: 'a@example.com' } })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(1))

    expect(sentResults(bridge)).toEqual([
      {
        id: 'new-customer',
        ok: false,
        message: 'Fix it',
        fieldErrors: { email: 'Already registered' },
      },
    ])
    surface.resolve({ ok: false, error: 'cancelled' })
    await pending
  })

  it('answers ok: false with the message of a thrown error', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const pending = showForm(customerForm, {
      onSubmit: async () => {
        throw new Error('The customer number is taken.')
      },
    })

    appCallsPage({ id: 'new-customer', action: 'submit', values: {} })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(1))

    expect(sentResults(bridge)).toEqual([
      { id: 'new-customer', ok: false, message: 'The customer number is taken.' },
    ])
    surface.resolve({ ok: false, error: 'cancelled' })
    await pending
  })

  it('takes field errors from a thrown error that carries them', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const pending = showForm(customerForm, {
      onSubmit: () => {
        throw Object.assign(new Error('Validation failed'), {
          fieldErrors: { name: 'Too short', ignored: 42 },
        })
      },
    })

    appCallsPage({ id: 'new-customer', action: 'submit' })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(1))

    expect(sentResults(bridge)).toEqual([
      {
        id: 'new-customer',
        ok: false,
        message: 'Validation failed',
        fieldErrors: { name: 'Too short' },
      },
    ])
    surface.resolve({ ok: false, error: 'cancelled' })
    await pending
  })

  it('treats a thrown string like an error message and a thrown object as failure', async () => {
    const { bridge, surface } = installSurfaceBridge()
    let attempt = 0
    const pending = showForm(customerForm, {
      onSubmit: () => {
        attempt += 1
        throw attempt === 1 ? 'Server said no' : { status: 500 }
      },
    })

    appCallsPage({ id: 'new-customer', action: 'submit' })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(1))
    appCallsPage({ id: 'new-customer', action: 'submit' })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(2))

    expect(sentResults(bridge)).toEqual([
      { id: 'new-customer', ok: false, message: 'Server said no' },
      { id: 'new-customer', ok: false },
    ])
    surface.resolve({ ok: false, error: 'cancelled' })
    await pending
  })

  it('lets the user correct and submit again, and passes then with success', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const created = { showContent: { title: 'Created', blocks: [] } }
    const onSubmit = vi
      .fn()
      .mockResolvedValueOnce({ fieldErrors: { email: 'Already registered' } })
      .mockResolvedValueOnce({ message: 'Saved', then: [created] })
    const pending = showForm(customerForm, { onSubmit })

    appCallsPage({ id: 'new-customer', action: 'submit', values: { email: 'a@example.com' } })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(1))
    appCallsPage({ id: 'new-customer', action: 'submit', values: { email: 'b@example.com' } })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(2))

    expect(sentResults(bridge)).toEqual([
      { id: 'new-customer', ok: false, fieldErrors: { email: 'Already registered' } },
      { id: 'new-customer', ok: true, message: 'Saved', then: [created] },
    ])
    surface.resolve({ ok: true, id: 'new-customer', action: 'submit', values: {}, labels: {} })
    await pending
  })

  it('does not send then with a failure, and an empty fieldErrors is a success', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const outcomes = [
      { ok: false, message: 'No', then: [{ close: true as const }] },
      { fieldErrors: {}, then: [{ close: true as const }] },
    ]
    let call = 0
    const pending = showForm(customerForm, { onSubmit: () => outcomes[call++] })

    appCallsPage({ id: 'new-customer', action: 'submit' })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(1))
    appCallsPage({ id: 'new-customer', action: 'submit' })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(2))

    expect(sentResults(bridge)).toEqual([
      { id: 'new-customer', ok: false, message: 'No' },
      { id: 'new-customer', ok: true, then: [{ close: true }] },
    ])
    surface.resolve({ ok: false, error: 'cancelled' })
    await pending
  })

  it('removes the handler when the promise settles', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const onSubmit = vi.fn()
    const pending = showForm(customerForm, { onSubmit })
    surface.resolve({ ok: false, error: 'cancelled' })
    expect(await pending).toEqual({ ok: false, error: 'cancelled' })

    appCallsPage({ id: 'new-customer', action: 'submit', values: {} })
    await Promise.resolve()
    await Promise.resolve()

    expect(onSubmit).not.toHaveBeenCalled()
    expect(sentResults(bridge)).toEqual([])
  })

  it('removes the handler when the app refuses (busy) and keeps another surface', async () => {
    const first = installSurfaceBridge()
    const open = showForm(customerForm, { onSubmit: vi.fn() })

    // The same id again: answered `busy` without asking the app, and the
    // handler of the open surface survives.
    const again = await showForm(customerForm, { onSubmit: vi.fn() })
    expect(again).toMatchObject({ ok: false, error: 'busy' })
    expect(first.bridge.call).toHaveBeenCalledTimes(1)

    appCallsPage({ id: 'new-customer', action: 'submit' })
    await vi.waitFor(() => expect(sentResults(first.bridge)).toHaveLength(1))
    first.surface.resolve({ ok: false, error: 'cancelled' })
    await open
  })

  it('removes the handler when the app answers busy for another surface', async () => {
    const bridge = installBridge({ call: vi.fn(async () => ({ ok: false, error: 'busy' })) })
    const onSubmit = vi.fn()
    expect(await showForm({ ...customerForm, id: 'busy-one' }, { onSubmit })).toEqual({
      ok: false,
      error: 'busy',
    })

    appCallsPage({ id: 'busy-one', action: 'submit' })
    await Promise.resolve()

    expect(onSubmit).not.toHaveBeenCalled()
    expect(sentResults(bridge)).toEqual([])
  })

  it('drops the late answer of an attempt that a newer one has replaced', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const slow = deferred<undefined>()
    let attempt = 0
    const pending = showForm(customerForm, {
      // First attempt hangs (the app times out after 60 s and re-enables the
      // button), the second one answers right away.
      onSubmit: () => (++attempt === 1 ? slow.promise : { fieldErrors: { name: 'Taken' } }),
    })

    appCallsPage({ id: 'new-customer', action: 'submit' })
    appCallsPage({ id: 'new-customer', action: 'submit' })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(1))
    slow.resolve(undefined)
    await Promise.resolve()
    await Promise.resolve()

    expect(sentResults(bridge)).toEqual([
      { id: 'new-customer', ok: false, fieldErrors: { name: 'Taken' } },
    ])
    surface.resolve({ ok: false, error: 'cancelled' })
    await pending
  })

  it('does not answer for a surface that was closed meanwhile', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const slow = deferred<undefined>()
    const pending = showForm(customerForm, { onSubmit: () => slow.promise })

    appCallsPage({ id: 'new-customer', action: 'submit' })
    surface.resolve({ ok: false, error: 'cancelled' }) // e.g. closeSurface or navigation
    await pending
    slow.resolve(undefined)
    await Promise.resolve()
    await Promise.resolve()

    expect(sentResults(bridge)).toEqual([])
  })

  it('ignores actions of surfaces it does not know and malformed events', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const onSubmit = vi.fn()
    const pending = showForm(customerForm, { onSubmit })

    appCallsPage({ id: 'someone-elses', action: 'submit' })
    appCallsPage(null as unknown as NativeSurfaceActionEvent)
    appCallsPage('submit' as unknown as NativeSurfaceActionEvent)
    await Promise.resolve()

    expect(onSubmit).not.toHaveBeenCalled()
    expect(sentResults(bridge)).toEqual([])
    surface.resolve({ ok: false, error: 'cancelled' })
    await pending
  })

  it('works next to listeners of on("surfaceAction") and a function set before', async () => {
    const { surface } = installSurfaceBridge()
    const seen = vi.fn()
    const off = on('surfaceAction', seen)
    const pending = showForm(customerForm, { onSubmit: () => {} })

    appCallsPage({ id: 'new-customer', action: 'submit', values: { name: 'x' } })
    expect(seen).toHaveBeenCalledWith({
      id: 'new-customer',
      action: 'submit',
      values: { name: 'x' },
    })

    off()
    surface.resolve({ ok: false, error: 'cancelled' })
    await pending
  })
})

describe('round trip: several loaded copies of the package', () => {
  it('lets every copy answer its own surfaces behind the single global', async () => {
    const bridge = installBridge({
      capabilities: ['nativeForms'],
      call: vi.fn(async (action: string) =>
        action === 'showForm' ? new Promise(() => {}) : { ok: true }
      ),
    })
    const onFirst = vi.fn(() => ({ message: 'first' }))
    void showForm({ ...customerForm, id: 'from-first-copy' }, { onSubmit: onFirst })

    vi.resetModules()
    const second = await import('../src/index.js')
    const onSecond = vi.fn(() => ({ message: 'second' }))
    void second.showForm({ ...customerForm, id: 'from-second-copy' }, { onSubmit: onSecond })

    appCallsPage({ id: 'from-second-copy', action: 'submit', values: { a: '1' } })
    appCallsPage({ id: 'from-first-copy', action: 'submit', values: { b: '2' } })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(2))

    expect(onFirst).toHaveBeenCalledTimes(1)
    expect(onSecond).toHaveBeenCalledTimes(1)
    expect(sentResults(bridge)).toEqual(
      expect.arrayContaining([
        { id: 'from-second-copy', ok: true, message: 'second' },
        { id: 'from-first-copy', ok: true, message: 'first' },
      ])
    )
  })
})

describe('round trip: showContent with onAction', () => {
  it('sets wait on the actions that do not have wait or then, without touching the input', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const def: NativeContentDef = {
      id: 'order-1',
      blocks: [
        { type: 'buttons', items: [{ id: 'approve', label: 'Approve' }] },
        {
          type: 'list',
          items: [
            { title: 'Row', action: { id: 'row-action', label: 'Row' } },
            { title: 'No action' },
          ],
        },
        {
          type: 'card',
          blocks: [
            {
              type: 'row',
              blocks: [{ type: 'buttons', items: [{ id: 'nested', label: 'Nested' }] }],
            },
          ],
        },
        { type: 'kpi', data: { value: 1 } },
      ],
      actions: [
        { id: 'save', label: 'Save', submit: true },
        { id: 'route', label: 'Route', then: [{ openUrl: 'https://example.com' }] },
        { id: 'later', label: 'Later', wait: false },
        { id: 'sure', label: 'Sure', wait: true, confirm: 'Sure?' },
      ],
    }
    const snapshot = structuredClone(def)

    const pending = showContent(def, { onAction: () => {} })

    expect(bridge.call).toHaveBeenCalledWith('showContent', {
      id: 'order-1',
      blocks: [
        { type: 'buttons', items: [{ id: 'approve', label: 'Approve', wait: true }] },
        {
          type: 'list',
          items: [
            { title: 'Row', action: { id: 'row-action', label: 'Row', wait: true } },
            { title: 'No action' },
          ],
        },
        {
          type: 'card',
          blocks: [
            {
              type: 'row',
              blocks: [{ type: 'buttons', items: [{ id: 'nested', label: 'Nested', wait: true }] }],
            },
          ],
        },
        { type: 'kpi', data: { value: 1 } },
      ],
      actions: [
        { id: 'save', label: 'Save', submit: true, wait: true },
        { id: 'route', label: 'Route', then: [{ openUrl: 'https://example.com' }] },
        { id: 'later', label: 'Later', wait: false },
        { id: 'sure', label: 'Sure', wait: true, confirm: 'Sure?' },
      ],
    })
    expect(def).toEqual(snapshot)
    surface.resolve({ ok: true, id: 'order-1', action: 'dismiss' })
    await pending
  })

  it('hands the tapped action to the handler and answers', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const onAction = vi.fn(async () => ({ message: 'Approved', then: [{ close: true as const }] }))
    const pending = showContent(
      { blocks: [], actions: [{ id: 'approve', label: 'Approve' }] },
      { onAction }
    )
    const id = (bridge.call.mock.calls[0]![1] as NativeContentDef).id as string
    expect(id).toEqual(expect.any(String))

    appCallsPage({ id, action: 'approve', values: { comment: 'ok' }, context: { n: 1 } })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(1))

    expect(onAction).toHaveBeenCalledWith({
      id,
      action: 'approve',
      values: { comment: 'ok' },
      context: { n: 1 },
    })
    expect(sentResults(bridge)).toEqual([
      { id, ok: true, message: 'Approved', then: [{ close: true }] },
    ])
    surface.resolve({ ok: true, id, action: 'approve' })
    expect(await pending).toEqual({ ok: true, id, action: 'approve' })
  })

  it('maps a thrown error to ok: false', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const pending = showContent(
      { id: 'order-2', blocks: [] },
      {
        onAction: async () => {
          throw new Error('Not allowed')
        },
      }
    )

    appCallsPage({ id: 'order-2', action: 'approve' })
    await vi.waitFor(() => expect(sentResults(bridge)).toHaveLength(1))

    expect(sentResults(bridge)).toEqual([{ id: 'order-2', ok: false, message: 'Not allowed' }])
    surface.resolve({ ok: true, id: 'order-2', action: 'dismiss' })
    await pending
  })

  it('without onAction nothing is changed and no handler is registered', async () => {
    const { bridge, surface } = installSurfaceBridge()
    const def: NativeContentDef = {
      blocks: [{ type: 'buttons', items: [{ id: 'a', label: 'A' }] }],
    }
    const pending = showContent(def)
    expect(bridge.call).toHaveBeenCalledWith('showContent', def)
    surface.resolve({ ok: true, id: 'x', action: 'dismiss' })
    await pending
  })
})

describe('limit warnings', () => {
  const text = (n: number) => 'x'.repeat(n)
  const field = (i: number): NativeFormField => ({ id: `f${i}`, type: 'text' })

  it('are empty for a definition within the limits', () => {
    expect(formLimitWarnings(customerForm)).toEqual([])
    expect(contentLimitWarnings({ blocks: [{ type: 'divider' }] })).toEqual([])
  })

  it('name the form limits', () => {
    const limits = NATIVE_SURFACE_LIMITS
    const pages = Array.from({ length: limits.formPages + 1 }, (_, i) => ({ fields: [field(i)] }))
    expect(formLimitWarnings({ pages })).toEqual([
      expect.stringContaining(`${limits.formPages + 1} pages`),
    ])

    const many = Array.from({ length: limits.formFields + 1 }, (_, i) => field(i))
    expect(formLimitWarnings({ fields: many })).toEqual([expect.stringContaining('61 fields')])

    const options = Array.from({ length: limits.fieldOptions + 1 }, (_, i) => ({ value: `${i}` }))
    expect(formLimitWarnings({ fields: [{ id: 'big', type: 'select', options }] })).toEqual([
      expect.stringContaining('fields[0] (big): 201 options'),
    ])

    expect(formLimitWarnings({ fields: [customerForm.fields![0]!], pages: [] })).toEqual([
      expect.stringContaining('not both'),
    ])
  })

  it('name repeat, photo and size problems', () => {
    const inner = [{ id: 'qty', type: 'stepper' as const }]
    expect(
      formLimitWarnings({
        fields: [
          { id: 'lines', type: 'repeat', fields: inner, max: 51 },
          { id: 'card', type: 'photo', max: 11, maxDimension: 5000 },
        ],
        values: { lines: Array.from({ length: 51 }, () => ({ qty: 1 })) },
      })
    ).toEqual([
      expect.stringContaining('repeat max 51'),
      expect.stringContaining('photo max 11'),
      expect.stringContaining('maxDimension 5000'),
      expect.stringContaining('values.lines: 51 rows'),
    ])

    expect(formLimitWarnings({ text: text(NATIVE_SURFACE_LIMITS.definitionBytes + 1) })).toEqual([
      expect.stringContaining('bytes'),
    ])
  })

  it('count the bytes of the definition in UTF-8', () => {
    // "ü" is two bytes in UTF-8: fewer characters than the limit, more bytes.
    const umlauts = 'ü'.repeat(NATIVE_SURFACE_LIMITS.definitionBytes / 2 + 1)
    expect(formLimitWarnings({ text: umlauts })).toEqual([expect.stringContaining('bytes')])
  })

  it('name the content limits', () => {
    const limits = NATIVE_SURFACE_LIMITS
    const blocks = Array.from({ length: limits.contentBlocks + 1 }, () => ({
      type: 'divider' as const,
    }))
    expect(contentLimitWarnings({ blocks })).toEqual([expect.stringContaining('101 blocks')])

    const deep = (levels: number): NativeContentDef => {
      let block: NativeContentDef['blocks'][number] = { type: 'divider' }
      for (let i = 0; i < levels; i++) block = { type: 'card', blocks: [block] }
      return { blocks: [block] }
    }
    expect(contentLimitWarnings(deep(limits.contentNesting))).toEqual([])
    expect(contentLimitWarnings(deep(limits.contentNesting + 1))).toEqual([
      expect.stringContaining('nested 4 deep'),
    ])

    const actions = Array.from({ length: 5 }, (_, i) => ({ id: `a${i}`, label: 'A' }))
    expect(contentLimitWarnings({ blocks: [], actions })).toEqual([
      expect.stringContaining('5 footer actions'),
    ])
  })

  it('check inline images one by one and in total', () => {
    const image = (bytes: number) => ({
      type: 'image' as const,
      data: `data:image/png;base64,${'A'.repeat(Math.ceil((bytes * 4) / 3))}`,
    })
    expect(contentLimitWarnings({ blocks: [image(1000)] })).toEqual([])
    expect(contentLimitWarnings({ blocks: [image(1024 * 1024 + 100)] })).toContainEqual(
      expect.stringContaining('blocks[0]: inline image')
    )
    const five = Array.from({ length: 5 }, () => image(1024 * 1024 - 100))
    const warnings = contentLimitWarnings({ blocks: five })
    expect(warnings.some((w) => w.includes('add up'))).toBe(true)
    expect(warnings.some((w) => w.startsWith('blocks[0]'))).toBe(false)
  })

  it('check the fields inside a content definition and the chain depth', () => {
    const options = Array.from({ length: 201 }, (_, i) => ({ value: `${i}` }))
    expect(
      contentLimitWarnings({
        blocks: [{ type: 'fields', fields: [{ id: 'big', type: 'multiselect', options }] }],
      })
    ).toEqual([expect.stringContaining('blocks[0].fields[0] (big): 201 options')])

    let content: NativeContentDef = { blocks: [] }
    for (let i = 0; i < 6; i++) {
      content = {
        blocks: [],
        actions: [{ id: 'next', label: 'Next', then: [{ showContent: content }] }],
      }
    }
    expect(contentLimitWarnings(content)).toEqual([expect.stringContaining('6 chained')])
  })
})

describe('warnings in the console', () => {
  let warn: ReturnType<typeof vi.spyOn>
  beforeEach(() => {
    warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  const tooManyFields: NativeFormDef = {
    fields: Array.from({ length: 61 }, (_, i) => ({ id: `f${i}`, type: 'text' as const })),
  }

  it('are logged in development builds, and the call still goes through', async () => {
    const bridge = installBridge()
    await showForm(tooManyFields)
    expect(warn).toHaveBeenCalledTimes(1)
    expect(warn.mock.calls[0]![0]).toMatch(/^\[@bmsuisse\/app-native\] showForm: 61 fields/)
    expect(bridge.call).toHaveBeenCalledWith('showForm', tooManyFields)

    await showContent({ blocks: Array.from({ length: 101 }, () => ({ type: 'divider' as const })) })
    expect(warn).toHaveBeenCalledTimes(2)
    expect(warn.mock.calls[1]![0]).toMatch(/showContent: 101 blocks/)
  })

  it('are off in a production build and when asked to', async () => {
    installBridge()
    vi.stubEnv('NODE_ENV', 'production')
    await showForm(tooManyFields)
    expect(warn).not.toHaveBeenCalled()

    vi.unstubAllEnvs()
    await showForm(tooManyFields, { validate: false })
    expect(warn).not.toHaveBeenCalled()

    vi.stubEnv('NODE_ENV', 'production')
    await showForm(tooManyFields, { validate: true })
    expect(warn).toHaveBeenCalledTimes(1)
  })

  it('are logged outside the app as well, so they show up while developing', async () => {
    expect(await showForm(tooManyFields)).toEqual({ ok: false, error: 'unavailable' })
    expect(warn).toHaveBeenCalledTimes(1)
  })
})

describe('types', () => {
  it('knows the field types and rejects what does not exist', () => {
    const fields: NativeFormField[] = [
      { id: 'a' }, // no type: text
      { id: 'b', type: 'segmented', options: [{ value: 'x' }] },
      { id: 'c', type: 'repeat', fields: [{ id: 'd', type: 'stepper', step: 5 }] },
    ]
    // @ts-expect-error there is no password field
    const password: NativeFormField = { id: 'p', type: 'password' }
    const photoInRepeat: NativeFormField = {
      id: 'r',
      type: 'repeat',
      // @ts-expect-error a repeat group cannot hold a photo
      fields: [{ id: 'p', type: 'photo' }],
    }
    // @ts-expect-error a segmented control needs its options
    const noOptions: NativeFormField = { id: 's', type: 'segmented' }
    expect([fields, password, photoInRepeat, noOptions]).toHaveLength(4)
  })
})
