# bmsapp-native

Everything web apps and backends need to talk to the **BMS app** (iOS): built once, used by everyone.

| Package                                             | For              | Contents                                                                                                                                                                                                   |
| --------------------------------------------------- | ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`@bmsuisse/app-native`](packages/app-native) (npm) | Web apps         | Typed calls to `window.BMSNative` (chrome, toast, share, scan, widgets, Live Activities, approvals, sign-in token, device actions, native forms and content) with browser fallbacks                        |
| [`bmsdna-app-native`](python/app-native) (Python)   | FastAPI backends | Push (APNs), sign-in with the Entra token, routers for devices/location, documents (incl. uploads of native forms), push actions, widgets, Live Activities, approvals, models for native forms and content |

The iOS app itself lives in a separate repository. It is the other side of this standard.

## Layout

```
packages/app-native/   @bmsuisse/app-native   (TypeScript, bun)
python/app-native/     bmsdna-app-native      (Python, uv; import: bmsdna.app_native)
contract-fixtures/     shared example payloads, tested by both sides
e2e/                   Playwright: the built npm package in a browser against the Python models
docs/                  one guide per topic (widgets, chrome, native forms and content, Live Activities, …)
```

The agent skill for projects that use the packages (`bmsapp-native`, part of the `coding` plugin) lives in [bmsuisse/skills](https://github.com/bmsuisse/skills/tree/main/skills/bmsapp-native), together with all other BMS skills.

The message format is maintained by hand on both sides. `contract-fixtures/` and the browser tests in `e2e/` keep them in sync, see [contract-fixtures/README.md](contract-fixtures/README.md) and [e2e/README.md](e2e/README.md).

## Installation

```bash
npm install @bmsuisse/app-native   # or: bun add @bmsuisse/app-native
uv add bmsdna-app-native           # or: pip install bmsdna-app-native
```

## Development

```bash
bun install
uv sync
prek install          # pre-commit hooks (ruff, ty, prettier, eslint, bun check)
```

```bash
bun run check         # typecheck + eslint + vitest
bun run build
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run pytest
cd e2e && uv sync && uv run pytest   # browser tests, see e2e/README.md
```

## Releasing

Each package is versioned independently. Bump the version in `packages/app-native/package.json` or `python/app-native/pyproject.toml` in a pull request and merge it. The [release workflow](.github/workflows/release.yml) runs the full CI on `main`, publishes to npm and PyPI, then tags the release.

## Contributing

Branch from `main`, open a pull request against `main`. Details for coding agents in [AGENTS.md](AGENTS.md).

## License

[MIT](LICENSE)
