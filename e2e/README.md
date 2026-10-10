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

## The fake bridge

`page/index.html` sets up `window.BMSNative` like the app and forwards every
message to the harness. For native surfaces (`showForm`, `showContent`) it also
plays the sheets: tests script what "the user" does with
`window.__surfaces.script`, and the fake checks capabilities and `busy`, uploads
media to the real document router, calls `window.onNativeSurfaceAction` for a
round trip and takes the page's `surfaceResult`. `/?capabilities=a,b` replaces
the capability list, `/?browser=1` removes `BMSNative`.

## What is tested

| Test                                                                                                                                                            | What                                                                                                                                                                                                         |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `test_feed_widgets_round_trip`                                                                                                                                  | Python feed → web app → `setWidgets` → Python models, nothing discarded                                                                                                                                      |
| `test_invalid_widget_is_rejected`                                                                                                                               | invalid widgets are counted individually                                                                                                                                                                     |
| `test_live_activity_lifecycle`                                                                                                                                  | start, update, invalid state, running ids                                                                                                                                                                    |
| `test_fire_and_forget_messages_reach_the_app`                                                                                                                   | `setChrome`, `toast`, `haptic` arrive with `action`                                                                                                                                                          |
| `test_app_callbacks_reach_listeners`                                                                                                                            | app callbacks (`onNativeMenuSelect`, …) reach `on()`                                                                                                                                                         |
| `test_browser_without_app`                                                                                                                                      | without `BMSNative`: no errors, `unavailable` responses                                                                                                                                                      |
| `test_get_access_token_and_call_the_backend_with_it`                                                                                                            | `getAccessToken`, then `fetch` with `Authorization: Bearer` against `create_entra_auth_dependency`                                                                                                           |
| `test_the_token_is_exchanged_for_a_cookie_the_page_cannot_read`                                                                                                 | the cookie in the browser (`HttpOnly`, `Secure`, `Lax`, host-only), then an `<img>` and `fetch` work without a header                                                                                        |
| `test_the_cookie_is_replaced_when_another_user_signs_in`                                                                                                        | a token of another user replaces the cookie                                                                                                                                                                  |
| `test_an_invalid_token_is_401_and_sets_no_cookie`, `test_a_valid_cookie_does_not_rescue_an_invalid_token`                                                       | expired / foreign-audience token: 401, no cookie                                                                                                                                                             |
| `test_browser_without_app_has_no_token_and_no_access`                                                                                                           | without the app: `getAccessToken` is `unavailable`, the backend says 401                                                                                                                                     |
| `test_websocket_takes_the_token_in_the_first_message`                                                                                                           | the browser way: token as first message                                                                                                                                                                      |
| `test_websocket_handshake_with_the_bearer_header`                                                                                                               | the app's way: token in the handshake header (Python client)                                                                                                                                                 |
| `test_device_actions_reach_the_app`                                                                                                                             | `navigate`, `addReminder`, `saveContact`, `callPhone` arrive with their fields                                                                                                                               |
| `test_navigate_in_a_browser_…`, `test_call_phone_in_a_browser_…`, `test_reminder_and_contact_…`                                                                 | the fallbacks without the app                                                                                                                                                                                |
| `test_show_form_returns_values_and_labels`, `test_an_invalid_definition_is_refused_like_the_app_does`                                                           | `showForm` with scripted results; definitions are validated with `NativeForm` / `NativeContent`                                                                                                              |
| `test_round_trip_with_a_field_error_and_then_success`, `test_a_thrown_error_keeps_the_form_open`, `test_content_action_round_trip`                              | `onSubmit` / `onAction`: `onNativeSurfaceAction` → backend → `surfaceResult`, field errors, thrown errors, handler cleanup                                                                                   |
| `test_fallback_to_the_web_ui_without_the_capability`, `test_fallback_in_a_browser_without_the_app`, `test_an_older_app_answers_unknown_action`                  | `capability`, `unavailable`, `unknownAction` and the web UI fallback                                                                                                                                         |
| `test_cancelled_busy_and_close_surface`, `test_chained_flow_from_…`                                                                                             | `cancelled`, `busy`, `closeSurface`, chained flows (`next`)                                                                                                                                                  |
| `test_photos_are_uploaded_by_the_app_…`, `test_without_an_id_from_the_router_…`, `test_the_same_upload_twice_is_one_file`, `test_an_unknown_reference_is_422_…` | the multipart upload to the document router (`kind="form"`, `upload_id`, `form_id`, `field_id`, `context`), with and without an `id`, idempotent per `upload_id`, references resolved by `resolve_file_refs` |
| `test_option_lookups_of_a_native_form_carry_form_id_and_context`, `test_limit_warnings_reach_the_console_…`                                                     | `form_id` + `context` at the options router; dev warnings for limits                                                                                                                                         |
| `test_date_helpers_use_the_time_zone_of_the_browser`                                                                                                            | `toIsoWithOffset`, `toDateOnly` (time zone fixed to Europe/Zurich)                                                                                                                                           |

## Debugging

- Append `--headed --slowmo 500` to `uv run pytest` to watch.
- Videos of failed tests end up in `test-results/` (gitignored).
