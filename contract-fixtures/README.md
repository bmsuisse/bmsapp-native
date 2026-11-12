# contract-fixtures

Shared sample payloads for both packages. The message format is written
**by hand** on both sides (TypeScript types in `packages/app-native/src`,
Pydantic models in `python/app-native`) — these files keep the two in sync:

- `python/app-native/tests/test_contract_fixtures.py` validates each file
  with the Pydantic models and checks that it serializes back unchanged.
- `packages/app-native/test/contract.test.ts` builds the same payloads as
  typed TS objects (the compiler checks them against the types) and
  compares them with these files.

| File                         | Contents                                                                 |
| ---------------------------- | ------------------------------------------------------------------------ |
| `widgets.json`               | dashboard widgets of every kind (incl. `web`) and the newer form fields  |
| `approvals.json`             | an approvals feed, incl. the BrAIn `conversationId`                      |
| `live-activity-state.json`   | a Live Activity state                                                    |
| `native-form.json`           | a native form (`showForm`) with every field type, pages, `submit`        |
| `native-content.json`        | native content (`showContent`) with every block type, actions, `then`    |
| `scan-result.json`           | `scanDocument` options and results (`NativeDocument`)                    |
| `pick-files.json`            | `pickFiles` options and results                                          |
| `documents-received.json`    | files shared into the web app: event payloads and `consume` results      |
| `dictate.json`               | `dictate` options and results                                            |
| `layout.json`                | `getLayout` results and `layoutChange` event payloads                    |
| `back-requested.json`        | `setBackInterception`, `onNativeBackRequested` and `backResult` payloads |
| `preview-file.json`          | `previewFile` options and results                                        |
| `access-token-resource.json` | `getAccessToken({ resource })` options and results                       |

## The files of the 2026-11 contract

The first five files above are one payload each. The eight newer ones list **cases**
for calls with a response, in sections:

- `options` (or `setBackInterception`, `backResult`): what the page passes. `valid` cases
  must reach the app as they are (`sent`, if present, is what the app receives instead:
  `previewFile` sends the URL as an absolute one); `invalid` cases carry the `error`
  that is expected, always `invalid`.
- `results` (or `consume`): what the app answers. `valid` cases come back from the
  package unchanged; `invalid` ones are malformed answers, which the package reports as
  `error: "failed"`.
- `events`: payloads of the calls from the app into the page. `invalid` ones are
  ignored (`error: "ignored"`).

Each case is `{ "name", "value", ["sent"], ["error"] }`. Placeholders keep the files
short: `"{origin}"` is the origin of the web app's page, a string `"@N"` stands for N
characters of `x` (in `contextualStrings` for a list of N entries), and
`{ "@repeat": N, "of": template }` stands for a list of N copies of the template with `{k}`
replaced by 0 … N-1 (for the limits: 81 menu items, 301 sidebar items).

### The files of 2026-11b

They use the same sections, and a few more:

- `chrome`: parts of `setChrome` (title, menus of action buttons, search, segments, sidebar,
  undo). `setChrome` has no answer, so `invalid` means: the package warns in development
  builds (`chromeLimitWarnings`), the app drops the part, and a direct
  `BMSNative.call('setChrome', …)` is answered `invalid` by the harness.
- `events`, `menuExpand`: payloads of the calls from the app into the page, grouped by
  event (`events.search.valid`, …).
- `menuItems`: what `loadChildren` returns for the lazy item `send` of the second valid
  menu. Invalid ones are not answered (`error: "unanswered"`).
- `searchAnswer`: what `onSearch` returns for a page search. `error: "normalized"` means the
  package sends `sent` instead (51 options cut to 50, an `http` image left out).
- `fields`: form fields with the new options `live` and `source: "page"`; invalid ones are
  refused by the Pydantic models (`source: "page"` only belongs to `search`).
- `update`, `updateResults` (document viewer): `updateDocument` options and results.

Who checks what:

- `packages/app-native/test/contract-2026-11.test.ts` runs every case through the
  package against a mock bridge.
- `python/app-native/tests/test_contract_fixtures.py` validates the documents with
  `NativeDocument`, the `context` and `kind` with `NativeDocumentContext` and
  `DocumentKind`, and checks the shape of the files.
- `e2e/test_documents.py` sends every `options` case through the built package to
  the fake app, whose Python harness validates it independently: `valid` cases must
  reach it, `invalid` ones must be refused by the package **and** by the harness.

Whoever adds or renames a field adds it here as well — then the tests of
the side that has not caught up yet fail.
