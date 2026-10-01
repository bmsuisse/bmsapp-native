---
name: bmsapp-native
description: >
  Use when a web app or FastAPI backend should talk to the BMS app (iOS shell
  that hosts BMS web apps): native menu/action buttons/bottom bar, toast,
  haptics, share, Face ID confirmation, document or barcode scan, dashboard
  widgets, Live Activities, approvals, push notifications (APNs), sign-in with
  the app's Entra token, route/reminder/contact/phone call on the iPhone. Covers `@bmsuisse/app-native` (npm, frontend) and
  `bmsdna-app-native` (Python, backend). Use instead of hand-writing
  `window.BMSNative` / `window.webkit.messageHandlers` calls or copying
  APNs/widget code into the project. Triggers: "in the app", "native
  bridge", "BMSNative", "push to the app", "widget on the dashboard", "Live
  Activity", "approvals in the app", "iOS app", "Entra token", "sign-in in the
  app", "navigate to", "reminder on the iPhone".
---

# bmsapp-native — connecting web apps and backends to the BMS app

Two packages, one standard. Never create your own copies of them in the
project (e.g. a custom `nativeBridge.ts` or `ios_push.py`) — if something is missing, it belongs in the package.

| Side                        | Package                                         | Reference                                      |
| --------------------------- | ----------------------------------------------- | ---------------------------------------------- |
| Web app (browser/WKWebView) | `@bmsuisse/app-native`                          | [references/webapp.md](references/webapp.md)   |
| Backend (FastAPI)           | `bmsdna-app-native`, import `bmsdna.app_native` | [references/backend.md](references/backend.md) |

## Ground rules

1. **The page must also work without the app.** The npm functions have
   browser fallbacks; guard your own logic with `isNativeApp()` / `can(...)`.
2. **The app decides on capabilities.** Each web app has capabilities in the
   app configuration (`camera`, `customChrome`, `dashboardWidgets`, …).
   Without the capability, the app responds `{ ok: false, error: 'capability' }`.
3. **Face ID is UX only.** `biometricConfirm` does not replace an
   authorization check in the backend. The same goes for `user_email` in
   request bodies: take the caller from `auth_dependency` (`context.user`).
4. **Callbacks via `on(...)`**, not via your own `window.onNative…` functions.
5. **Widgets/Live Activities:** the same format via the bridge (npm), feed or
   push (Python). Use the Pydantic models in the backend, otherwise the app
   silently discards invalid widgets.
6. **Never commit APNs keys** (`.p8`); configure via `APNS_*` environment
   variables.
7. **Sign-in is the Entra token of the app**, not a cookie login of your own,
   for web apps with the `identity` capability. The backend checks the token
   (`create_entra_auth_dependency`), answers **401** for an invalid one (never
   a redirect), and takes the user from it. Never forward, store or log the
   token. Guide: `docs/entra-token-guide.md`.
8. **Reminders and contacts need `deviceApps`**; route and phone call do not.
   Guide: `docs/device-actions-guide.md`.
