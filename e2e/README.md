# E2E — Playwright

Tests the **built** `@bmsuisse/app-native` in a real browser against
`bmsdna-app-native`: a test page sets up `window.BMSNative` like the app,
but forwards every message to a FastAPI harness ([server.py](server.py)),
which validates the formats with the same Pydantic models backends use.
The real iOS app does not take part.

A separate uv project, **not** a workspace member, so Playwright and the
browser binaries never end up in a regular `uv sync`.

## Running

```bash
bun install                               # in the repo root, once
cd e2e
uv sync
uv run playwright install chromium        # once
uv run pytest
```

The npm package is built automatically before the tests (`bun run build`).

## What is tested

| Test                                                                                                      | What                                                                                                                  |
| --------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `test_feed_widgets_round_trip`                                                                            | Python feed → web app → `setWidgets` → Python models, nothing discarded                                               |
| `test_invalid_widget_is_rejected`                                                                         | invalid widgets are counted individually                                                                              |
| `test_live_activity_lifecycle`                                                                            | start, update, invalid state, running ids                                                                             |
| `test_fire_and_forget_messages_reach_the_app`                                                             | `setChrome`, `toast`, `haptic` arrive with `action`                                                                   |
| `test_app_callbacks_reach_listeners`                                                                      | app callbacks (`onNativeMenuSelect`, …) reach `on()`                                                                  |
| `test_browser_without_app`                                                                                | without `BMSNative`: no errors, `unavailable` responses                                                               |
| `test_get_access_token_and_call_the_backend_with_it`                                                      | `getAccessToken`, then `fetch` with `Authorization: Bearer` against `create_entra_auth_dependency`                    |
| `test_the_token_is_exchanged_for_a_cookie_the_page_cannot_read`                                           | the cookie in the browser (`HttpOnly`, `Secure`, `Lax`, host-only), then an `<img>` and `fetch` work without a header |
| `test_the_cookie_is_replaced_when_another_user_signs_in`                                                  | a token of another user replaces the cookie                                                                           |
| `test_an_invalid_token_is_401_and_sets_no_cookie`, `test_a_valid_cookie_does_not_rescue_an_invalid_token` | expired / foreign-audience token: 401, no cookie                                                                      |
| `test_browser_without_app_has_no_token_and_no_access`                                                     | without the app: `getAccessToken` is `unavailable`, the backend says 401                                              |
| `test_websocket_takes_the_token_in_the_first_message`                                                     | the browser way: token as first message                                                                               |
| `test_websocket_handshake_with_the_bearer_header`                                                         | the app's way: token in the handshake header (Python client)                                                          |
| `test_device_actions_reach_the_app`                                                                       | `navigate`, `addReminder`, `saveContact`, `callPhone` arrive with their fields                                        |
| `test_navigate_in_a_browser_…`, `test_call_phone_in_a_browser_…`, `test_reminder_and_contact_…`           | the fallbacks without the app                                                                                         |
| `test_date_helpers_use_the_time_zone_of_the_browser`                                                      | `toIsoWithOffset`, `toDateOnly` (time zone fixed to Europe/Zurich)                                                    |

## Debugging

- Append `--headed --slowmo 500` to `uv run pytest` to watch.
- Videos of failed tests end up in `test-results/` (gitignored).
