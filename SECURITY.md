# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Use GitHub's private vulnerability reporting instead: open the **Security** tab
of this repository and choose **Report a vulnerability**. Include what you
found, how to reproduce it and which version is affected. We will confirm the
report and keep you updated until a fix is released.

## Supported versions

Only the latest released version of `@bmsuisse/app-native` (npm) and
`bmsdna-app-native` (PyPI) receives security fixes.

## For integrators

- Every `create_*_router()` requires an `auth_dependency`. `insecure_no_auth`
  is an explicit opt-out for local development and tests only — never use it on
  a host that is reachable from a network.
- Identity comes from `context.user` (what your `auth_dependency` returned).
  Fields in the request body such as `user_email`, `device_id`, `approval_id` or
  `activity_id` are client input: check that `context.user` may act on them
  before you route pushes, approvals or documents by them.
- The example app under `python/app-native/example/` is a local demo with
  in-memory storage and no per-user ownership checks. It is not a deployment
  template.
- Keep the APNs key (`APNS_KEY`) and `SESSION_SECRET` in a secret store, never
  in the repository or in logs.
