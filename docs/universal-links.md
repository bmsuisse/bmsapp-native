# Universal Links

With Universal Links, a link to a web app domain that someone taps in
Outlook, Teams or an email opens the matching web app directly in the
BMS app, at exactly that location. Without them, the link ends up in
Safari. If the app isn't installed, the link opens in Safari as before.

This only works for domains that are registered in the app as an Associated
Domain.

## What every web app must do

Your server must serve this file at
`https://<domain>/.well-known/apple-app-site-association` (no file
extension, `Content-Type: application/json`, no redirect):

```json
{
  "applinks": {
    "details": [
      {
        "appIDs": ["<TEAM_ID>.<BUNDLE_ID>"],
        "components": [
          { "/": "/api/*", "exclude": true },
          { "/": "/.auth/*", "exclude": true },
          { "/": "/*" }
        ]
      }
    ]
  }
}
```

`<TEAM_ID>` and `<BUNDLE_ID>` are the app's team ID and bundle ID.

The `exclude` entries make sure that API and login callback URLs never open
the app. Which paths you need to exclude depends on your backend. Use
`components` to restrict the paths so that only links that really belong in
the app go there.

FastAPI example:

```python
from fastapi.responses import JSONResponse

AASA = {...}  # see above


@app.get("/.well-known/apple-app-site-association", include_in_schema=False)
def apple_app_site_association():
    return JSONResponse(AASA)
```

This route must not require authentication: Apple fetches it through its CDN
without a session.

## Testing

- Apple caches the file. After a change, it can take up to 24 h until iOS
  sees it. To check the current state:
  `https://app-site-association.cdn-apple.com/a/v1/<domain>`
- Links typed directly into the Safari address bar never open the app. To
  test, tap the link in Notes or in an email.
- Links within the app (in the WebView) always stay in the WebView.
