// The fixtures of the 2026-11b contract (contract-fixtures/*.json, see the README
// there) run through the package, like contract-2026-11.test.ts does for 2026-11.

import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import {
  FEATURES,
  chromeLimitWarnings,
  on,
  setChrome,
  setKeyCommands,
  setKeyboardToolbar,
  showAlert,
  showDocument,
  showForm,
  showMenu,
  showPicker,
  toast,
  updateDocument,
  updateSurface,
  type Chrome,
  type NativeEvent,
  type NativeFormField,
} from '../src/index.js'
import menuJson from '../../../contract-fixtures/menu.json'
import alertJson from '../../../contract-fixtures/alert.json'
import toastJson from '../../../contract-fixtures/toast-action.json'
import liveJson from '../../../contract-fixtures/live-surface.json'
import navSearchJson from '../../../contract-fixtures/nav-search.json'
import keyboardJson from '../../../contract-fixtures/keyboard-toolbar.json'
import segmentsJson from '../../../contract-fixtures/segments.json'
import sidebarJson from '../../../contract-fixtures/sidebar.json'
import documentJson from '../../../contract-fixtures/document-viewer.json'
import undoJson from '../../../contract-fixtures/undo.json'
import pickerJson from '../../../contract-fixtures/picker.json'
import keyCommandsJson from '../../../contract-fixtures/key-commands.json'
import { installBridge as installUntyped, removeBridge } from './helpers.js'

afterEach(() => {
  vi.useRealTimers()
  removeBridge()
})

type Case = { name: string; value: unknown; sent?: unknown; error?: string }
type Section = { valid?: Case[]; invalid?: Case[] }

type Bridge = { call: Mock; postMessage: Mock }

function install(overrides: Parameters<typeof installUntyped>[0] = {}) {
  return installUntyped({
    features: [...FEATURES],
    capabilities: ['customChrome', 'camera', 'nativeForms', 'nativeContent'],
    ...overrides,
  }) as unknown as Bridge
}

const flush = async () => {
  for (let i = 0; i < 8; i++) await Promise.resolve()
}

function answer(result: unknown) {
  return vi.fn(async (_action: string, _payload?: Record<string, unknown>) => result)
}

/** `"@N"`: N characters, `{ "@repeat": N, "of": template }`: N copies with `{k}` replaced. */
function fill(template: unknown, k: number): unknown {
  if (typeof template === 'string') return template.replaceAll('{k}', String(k))
  if (Array.isArray(template)) return template.map((v) => fill(v, k))
  if (typeof template === 'object' && template !== null) {
    return Object.fromEntries(Object.entries(template).map(([key, v]) => [key, fill(v, k)]))
  }
  return template
}

function expand(value: unknown, key = ''): unknown {
  if (typeof value === 'string' && /^@\d+$/.test(value)) {
    const n = Number(value.slice(1))
    return key === 'contextualStrings' ? Array.from({ length: n }, () => 'a') : 'x'.repeat(n)
  }
  if (Array.isArray(value)) return value.map((v) => expand(v))
  if (typeof value === 'object' && value !== null) {
    const record = value as Record<string, unknown>
    if ('@repeat' in record) {
      return Array.from({ length: record['@repeat'] as number }, (_, k) =>
        fill(expand(record.of), k)
      )
    }
    return Object.fromEntries(Object.entries(record).map(([k, v]) => [k, expand(v, k)]))
  }
  return value
}

const withOrigin = (value: unknown): unknown =>
  JSON.parse(JSON.stringify(value).replaceAll('{origin}', window.location.origin))

const prepare = (value: unknown) => withOrigin(expand(value))

/** Valid options reach the app as they are, invalid ones never reach it. */
function runOptions(
  title: string,
  section: Section | undefined,
  action: string,
  run: (value: never) => Promise<unknown>
) {
  describe(`${title}: options`, () => {
    for (const c of section?.valid ?? []) {
      it(`valid: ${c.name}`, async () => {
        const bridge = install({ call: answer({ ok: false, error: 'cancelled' }) })
        await run(prepare(c.value) as never)
        expect(bridge.call).toHaveBeenCalledTimes(1)
        expect(bridge.call).toHaveBeenCalledWith(action, prepare(c.sent ?? c.value))
      })
    }
    for (const c of section?.invalid ?? []) {
      it(`invalid: ${c.name}`, async () => {
        vi.spyOn(console, 'warn').mockImplementation(() => {})
        const bridge = install()
        expect(await run(prepare(c.value) as never)).toMatchObject({ ok: false, error: c.error })
        expect(bridge.call).not.toHaveBeenCalled()
      })
    }
  })
}

/** What the app answers comes back as it is; a malformed answer is `failed`. */
function runResults(title: string, section: Section | undefined, run: () => Promise<unknown>) {
  describe(`${title}: results`, () => {
    for (const c of section?.valid ?? []) {
      it(`valid: ${c.name}`, async () => {
        install({ call: answer(c.value) })
        expect(await run()).toEqual(c.value)
      })
    }
    for (const c of section?.invalid ?? []) {
      it(`invalid: ${c.name}`, async () => {
        install({ call: answer(c.value) })
        expect(await run()).toMatchObject({ ok: false, error: c.error })
      })
    }
  })
}

/**
 * Parts of `setChrome`: valid ones are sent without a warning, invalid ones are sent
 * too (the app drops them) and the package warns in a development build.
 */
function runChrome(title: string, section: Section | undefined) {
  describe(`${title}: chrome`, () => {
    for (const c of section?.valid ?? []) {
      it(`valid: ${c.name}`, () => {
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
        const bridge = install()
        const chrome = prepare(c.value) as Chrome
        expect(chromeLimitWarnings(chrome)).toEqual([])
        setChrome(chrome)
        expect(bridge.postMessage).toHaveBeenCalledWith({ ...chrome, action: 'setChrome' })
        expect(warn).not.toHaveBeenCalled()
      })
    }
    for (const c of section?.invalid ?? []) {
      it(`invalid: ${c.name}`, () => {
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
        const bridge = install()
        const chrome = prepare(c.value) as Chrome
        expect(chromeLimitWarnings(chrome).length).toBeGreaterThan(0)
        setChrome(chrome)
        expect(bridge.postMessage).toHaveBeenCalledOnce()
        expect(warn).toHaveBeenCalled()
      })
    }
  })
}

/** The app calls the page: every valid payload reaches the listeners of `on(event)`. */
function runEvents(title: string, events: Record<string, Section> | undefined) {
  describe(`${title}: events`, () => {
    for (const [event, section] of Object.entries(events ?? {})) {
      for (const c of section.valid ?? []) {
        it(`${event}: ${c.name}`, () => {
          const seen: unknown[] = []
          const off = on(event as NativeEvent, (payload) => seen.push(payload))
          const globalName = `onNative${event[0]?.toUpperCase()}${event.slice(1)}`
          ;(window as unknown as Record<string, (p: unknown) => void>)[globalName]?.(c.value)
          expect(seen).toEqual([c.value])
          off()
        })
      }
    }
  })
}

// --- C11 -------------------------------------------------------------------------

runOptions('menu', menuJson.options as Section, 'showMenu', (o) => showMenu(o))
runResults('menu', menuJson.results as Section, () =>
  showMenu({
    anchor: { x: 0, y: 0, width: 1, height: 1 },
    sections: [{ items: [{ id: 'a', label: 'A' }] }],
  })
)
runChrome('menu', menuJson.chrome as Section)
runEvents('menu', menuJson.events as Record<string, Section>)

describe('menu: lazy answers', () => {
  const base = prepare((menuJson.options.valid as Case[])[1]?.value) as Parameters<
    typeof showMenu
  >[0]
  const run = async (sections: unknown) => {
    let finish!: (value: unknown) => void
    const shown = new Promise((resolve) => (finish = resolve))
    const bridge = install({
      call: vi.fn(async (action: string) => (action === 'showMenu' ? shown : { ok: true })),
    })
    const result = showMenu({ ...base, loadChildren: () => sections as never })
    ;(window as unknown as Record<string, (e: unknown) => void>).onNativeMenuExpand?.({
      menuId: 'offer-menu',
      itemId: 'send',
      requestId: 'r1',
    })
    await flush()
    finish({ ok: false, error: 'cancelled' })
    await result
    return bridge
  }

  for (const c of (menuJson.menuItems as Section).valid ?? []) {
    it(`valid: ${c.name}`, async () => {
      const bridge = await run(prepare(c.value))
      expect(bridge.call).toHaveBeenLastCalledWith('menuItems', {
        requestId: 'r1',
        sections: prepare(c.value),
      })
    })
  }
  for (const c of (menuJson.menuItems as Section).invalid ?? []) {
    it(`${c.error}: ${c.name}`, async () => {
      vi.spyOn(console, 'warn').mockImplementation(() => {})
      const bridge = await run(prepare(c.value))
      expect(bridge.call.mock.calls.map(([a]) => a)).toEqual(['showMenu'])
    })
  }
})

// --- C12 -------------------------------------------------------------------------

runOptions('alert', alertJson.options as Section, 'showAlert', (o) => showAlert(o))
runResults('alert', alertJson.results as Section, () =>
  showAlert({ title: 'T', actions: [{ id: 'a', label: 'A' }] })
)

// --- C13 -------------------------------------------------------------------------

runOptions('toast', toastJson.options as Section, 'toast', (o: { message: string }) => {
  const { message, ...rest } = o
  return toast(message, rest)
})
runResults('toast', toastJson.results as Section, () => toast('x', { duration: 2 }))
runEvents('toast', toastJson.events as Record<string, Section>)

// --- C14 -------------------------------------------------------------------------

runOptions('live-surface', liveJson.options as Section, 'updateSurface', (o) => updateSurface(o))
runResults('live-surface', liveJson.results as Section, () =>
  updateSurface({ id: 'f', title: 'x' })
)

describe('live-surface: fields', () => {
  for (const c of (liveJson.fields as Section).valid ?? []) {
    it(`valid: ${c.name}`, async () => {
      const bridge = install({ call: answer({ ok: false, error: 'cancelled' }) })
      await showForm({ fields: [c.value as NativeFormField] })
      expect(bridge.call).toHaveBeenCalledWith('showForm', { fields: [c.value] })
    })
  }
})

describe('live-surface: events', () => {
  const w = () => window as unknown as Record<string, (e: unknown) => void>

  for (const c of (liveJson.events as Record<string, Section>).surfaceChange?.valid ?? []) {
    it(`surfaceChange: ${c.name}`, async () => {
      let finish!: (value: unknown) => void
      install({ call: vi.fn(async () => new Promise((resolve) => (finish = resolve))) })
      const seen: unknown[] = []
      const { id, fieldId, value } = c.value as { id: string; fieldId: string; value: unknown }
      const pending = showForm(
        { id, fields: [{ id: fieldId, type: 'text' }] },
        { onChange: (f, v) => seen.push([f, v]) }
      )
      w().onNativeSurfaceChange?.(c.value)
      expect(seen).toEqual([[fieldId, value]])
      finish({ ok: false, error: 'cancelled' })
      await pending
    })
  }

  for (const c of (liveJson.events as Record<string, Section>).surfaceSearch?.valid ?? []) {
    it(`surfaceSearch: ${c.name}`, async () => {
      let finish!: (value: unknown) => void
      const bridge = install({
        call: vi.fn(async (action: string) =>
          action === 'showForm' ? new Promise((r) => (finish = r)) : { ok: true }
        ),
      })
      const event = c.value as { id: string; fieldId: string; query: string; requestId: string }
      const seen: unknown[] = []
      const pending = showForm(
        { id: event.id, fields: [{ id: event.fieldId, type: 'search', source: 'page' }] },
        { onSearch: (f, q) => (seen.push([f, q]), []) }
      )
      w().onNativeSurfaceSearch?.(c.value)
      await flush()
      expect(seen).toEqual([[event.fieldId, event.query]])
      expect(bridge.call).toHaveBeenLastCalledWith('surfaceSearchResult', {
        requestId: event.requestId,
        options: [],
      })
      finish({ ok: false, error: 'cancelled' })
      await pending
    })
  }
})

describe('live-surface: search answers', () => {
  const run = async (options: unknown) => {
    let finish!: (value: unknown) => void
    const bridge = install({
      call: vi.fn(async (action: string) =>
        action === 'showForm' ? new Promise((r) => (finish = r)) : { ok: true }
      ),
    })
    const pending = showForm(
      { id: 'f', fields: [{ id: 'customer', type: 'search', source: 'page' }] },
      { onSearch: () => options as never }
    )
    return {
      bridge,
      type: async (requestId: string) => {
        ;(window as unknown as Record<string, (e: unknown) => void>).onNativeSurfaceSearch?.({
          id: 'f',
          fieldId: 'customer',
          query: 'q',
          requestId,
        })
        await flush()
      },
      close: async () => {
        finish({ ok: false, error: 'cancelled' })
        await pending
      },
    }
  }
  const answers = liveJson.searchAnswer as Section

  for (const c of answers.valid ?? []) {
    it(`valid: ${c.name}`, async () => {
      const value = prepare(c.value) as { requestId: string; options: unknown[] }
      const { bridge, type, close } = await run(value.options)
      await type(value.requestId)
      expect(bridge.call).toHaveBeenLastCalledWith('surfaceSearchResult', value)
      await close()
    })
  }
  for (const c of answers.invalid ?? []) {
    it(`${c.error}: ${c.name}`, async () => {
      vi.spyOn(console, 'warn').mockImplementation(() => {})
      const value = prepare(c.value) as { requestId: string; options: unknown[] }
      const { bridge, type, close } = await run(value.options)
      await type(value.requestId)
      expect(bridge.call).toHaveBeenLastCalledWith('surfaceSearchResult', prepare(c.sent))
      await close()
    })
  }
})

// --- C15, C17, C18, C20: parts of setChrome ----------------------------------------

runChrome('nav-search', navSearchJson.chrome as Section)
runEvents('nav-search', navSearchJson.events as Record<string, Section>)
runChrome('segments', segmentsJson.chrome as Section)
runEvents('segments', segmentsJson.events as Record<string, Section>)
runChrome('sidebar', sidebarJson.chrome as Section)
runEvents('sidebar', sidebarJson.events as Record<string, Section>)
runChrome('undo', undoJson.chrome as Section)
runEvents('undo', undoJson.events as Record<string, Section>)

// --- C16 -------------------------------------------------------------------------

runOptions('keyboard-toolbar', keyboardJson.options as Section, 'setKeyboardToolbar', (o) =>
  setKeyboardToolbar(o)
)
runResults('keyboard-toolbar', keyboardJson.results as Section, () =>
  setKeyboardToolbar({ items: [] })
)
runEvents('keyboard-toolbar', keyboardJson.events as Record<string, Section>)

// --- C19 -------------------------------------------------------------------------

runOptions('document-viewer', documentJson.options as Section, 'showDocument', (o) =>
  showDocument(o)
)
runOptions('document-viewer update', documentJson.update as Section, 'updateDocument', (o) =>
  updateDocument(o)
)
runResults('document-viewer', documentJson.results as Section, () =>
  showDocument({ url: '/a.pdf' })
)
runResults('document-viewer update', documentJson.updateResults as Section, () =>
  updateDocument({ id: 'x' })
)
runEvents('document-viewer', documentJson.events as Record<string, Section>)

// --- C21, C22 ----------------------------------------------------------------------

runOptions('picker', pickerJson.options as Section, 'showPicker', (o) => showPicker(o))
runResults('picker', pickerJson.results as Section, () => showPicker({ kind: 'date' }))
runOptions('key-commands', keyCommandsJson.options as Section, 'setKeyCommands', (o) =>
  setKeyCommands(o)
)
runResults('key-commands', keyCommandsJson.results as Section, () =>
  setKeyCommands({ commands: [] })
)
runEvents('key-commands', keyCommandsJson.events as Record<string, Section>)
