# AGENTS.md · bmsapp-native

Rules for coding agents (Claude Code and others) in this repo.

## 1. What lives where

```
packages/app-native/   @bmsuisse/app-native   web app side (window.BMSNative)
python/app-native/     bmsdna-app-native      backend side (FastAPI, APNs)
contract-fixtures/     shared example payloads of both sides
e2e/                   Playwright: npm package in the browser against the Python models
docs/                  one guide per topic
skills/bmsapp-native/  skill for projects that use the packages
```

The iOS app lives in a separate repository and is the other side of this standard. The formats here have to match it.

## 2. The format is maintained by hand on both sides

There is no code generation. Whoever changes a field, an action or a widget changes **all** affected places in the same commit:

| What            | TypeScript              | Python                                 | Docs                              |
| --------------- | ----------------------- | -------------------------------------- | --------------------------------- |
| Widgets         | `src/widgets.ts`        | `bmsdna/app_native/widgets.py`         | `docs/dashboard-widgets-guide.md` |
| Live Activities | `src/liveActivities.ts` | `bmsdna/app_native/live_activities.py` | `docs/live-activities-guide.md`   |
| Chrome          | `src/chrome.ts`         | –                                      | `docs/webapp-chrome-guide.md`     |
| Bridge actions  | `src/*.ts`              | –                                      | guides + the package README       |

Also add the example to `contract-fixtures/`. The tests of both sides check against it (`test/contract.test.ts`, `tests/test_contract_fixtures.py`).

## 3. Checks before every push

| Changed                   | Required                                                                                  |
| ------------------------- | ----------------------------------------------------------------------------------------- |
| `packages/`               | `bun run check` and `bun run build`                                                       |
| `python/`                 | `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run pytest` |
| `contract-fixtures/`      | both                                                                                      |
| Bridge actions or formats | additionally `cd e2e && uv run pytest`                                                    |

Run `prek install` once; the hooks from `prek.toml` then run before every commit. CI (`.github/workflows/ci.yml`) runs the same checks on every pull request.

## 4. One change per commit

Commit per area (`app-native: …`, `python: …`, `docs: …`), except for format changes under rule 2, which belong together.

## 5. Never commit

`**/.env`, `**/.env.local`, `**/keys/*.p8` (APNs keys), `node_modules/`, `dist/`. The `.gitignore` covers this, do not work around it. Real hosts, tokens, team IDs or bundle IDs do not belong in docs, examples or tests either: use `example.com` and placeholders.

## 6. Branch naming

`feature/<short-descriptive-kebab-case>` or `fix/<…>`: describes what is being built, 3–6 words, lowercase, no random characters, ticket IDs, initials or date stamps. Start with the area where possible (`app-native`, `python`, `docs`). If the harness gives you another name, rename it before the first push. If unsure, ask first.

## 7. Branch workflow

Branch from `origin/main`:

```
git fetch origin
git checkout -b feature/<name> origin/main
```

1. Commit, then push: `git push -u origin feature/<name>`.
2. After each push, print a title and description for the pull request as a copy-paste block in the chat (from `git log origin/main..<branch>`). A human opens and merges the pull request.

Forbidden: pushing to `main`, and opening, changing or merging pull requests via CLI or MCP.

## 8. Releasing

Only when a human explicitly asks. Releases are made by the release workflow after a version bump has been merged to `main` (see the README). Never publish manually.
