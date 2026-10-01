# Approvals inbox for web app developers

At the top of the home dashboard, the app shows the **"Waiting for you"** card:
everything that is currently waiting for approval by the logged-in user, collected from
all web apps. Examples are vacation requests, expenses, orders
and overtime. The user can

- **approve**: swipe right in the list or tap
  "Approve" in the details, optionally with Face ID,
- **reject**: swipe left or tap "Reject" in the details,
  optionally with a mandatory reason,
- **view details** and jump from there into your web app.

Your web app does not need to be open for this. The number of pending approvals is
also shown as a red badge on the Home tab.

| Who                    | What                                                                                                                  |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **You (web app team)** | Which approvals are waiting for whom, what "Approve" and "Reject" do, who is allowed to do what. All in your backend. |
| **iOS app**            | Display, sorting (urgent and due first), swiping, comment prompt, Face ID, badge.                                     |

Backend side:
[`python/app-native/bmsdna/app_native/approvals.py`](../python/app-native/bmsdna/app_native/approvals.py).

## Prerequisite: capability

The app must have the `.approvals` capability enabled for your web app.
It calls the default paths `api/approvals` and
`api/approval-decisions`, unless different ones are configured for your web app.

Without `.approvals`, the app never queries your feed. If your backend returns
a 404 at that path, the card simply stays empty for you, without
an error message.

## The two endpoints

The app authenticates both calls the same way as the widget feed: web apps with
the `identity` capability get the Entra token of the app's sign-in as
`Authorization: Bearer …` (see [entra-token-guide.md](entra-token-guide.md)), the
others (for example pages on SharePoint) the cookie of their origin. Your
`auth_dependency` decides what it accepts, see the README of the Python package.
The app treats 401/403 or a redirect to a login page on the **feed** as "not signed
in": it clears that web app's approvals and shows a note to open the web app. A web app
that signs in with a cookie first gets one invisible sign-in and a retry. With a token,
a 401 first makes the app fetch a renewed token and repeat the call once. A **decision**
that gets 401/403 shows "open the web app and sign in" and clears nothing.

### `GET api/approvals?device_id=…`

Returns what is waiting for the user **right now**. The app uses it to replace all
of your web app's approvals. Anything you no longer return disappears.

```json
{
  "approvals": [
    {
      "id": "vac-17",
      "title": "Vacation request",
      "subtitle": "Anna Muster · 3–7 November",
      "category": "Vacation",
      "amount": "5 days",
      "requester": "Anna Muster",
      "createdAt": "2026-09-26T08:00:00Z",
      "dueAt": "2026-10-01T12:00:00Z",
      "urgent": false,
      "icon": "sun.max.fill",
      "details": [
        { "label": "Period", "value": "Mon 3 to Fri 7 November" },
        { "label": "Deputy", "value": "Beat Beispiel" }
      ],
      "path": "/vacation/17",
      "approveLabel": "Approve",
      "rejectLabel": "Reject",
      "approveComment": "none",
      "rejectComment": "required",
      "biometric": false
    }
  ]
}
```

| Field                             | Required | Meaning                                                                      |
| --------------------------------- | -------- | ---------------------------------------------------------------------------- |
| `id`                              | ✓        | Stable across fetches, comes back as `approval_id` with the decision         |
| `title`                           | ✓        | Bold in the list                                                             |
| `subtitle`                        |          | Second line, e.g. requester and period                                       |
| `category`                        |          | Small above the title, e.g. "Expenses"                                       |
| `amount`                          |          | Highlighted at the top right, e.g. `"CHF 1'240.50"`                          |
| `requester`                       |          | "Requested by" in the details                                                |
| `createdAt`, `dueAt`              |          | ISO 8601. With a deadline, the app shows "Due tomorrow" or "Overdue" in red  |
| `urgent`                          |          | Highlighted in red, at the very top                                          |
| `icon`                            |          | SF Symbol, default is your web app's icon                                    |
| `details`                         |          | Additional rows in the details, at most 12                                   |
| `path`                            |          | "Open in …" button in the details                                            |
| `approveLabel`, `rejectLabel`     |          | Button label, default "Approve"/"Reject"                                     |
| `approveComment`, `rejectComment` |          | `none`, `optional` or `required`. Default: approve `none`, reject `optional` |
| `biometric`                       |          | Approve only after Face ID/Touch ID                                          |

Sorting happens in the app: urgent first, then by deadline, then the oldest
requests. At most 100 approvals per web app.

### `POST api/approval-decisions`

```json
{
  "device_id": "…",
  "approval_id": "vac-17",
  "decision": "reject",
  "comment": "Too short notice",
  "user_email": "manager@example.com"
}
```

Response, all fields optional:

```json
{"ok": true, "message": "Rejected, Anna will be notified", "style": "success",
 "approvals": [ … ]}
```

- `ok: false` keeps the approval in place and shows `message` as an error,
  e.g. "Already handled by someone else".
- `approvals` replaces all of your web app's pending approvals. Without this field,
  the app removes only the one just decided.
- Without `message`, the app shows "Approved" or "Rejected".

**Important:** Check in your own backend whether this user is allowed to decide this
approval. `approval_id` and `user_email` come from the device (take the
user from your `auth_dependency`, not from `user_email`), and Face
ID is only a confirmation on the device, not proof for your backend.
Decisions deliberately do **not** go into the offline queue: without a
network, the user sees an error immediately.

## Refreshing

The app loads your approvals at launch, every time it returns to the
foreground (at most once per minute), after login and via
pull-to-refresh. In addition:

- **Silent push**: `send_approvals_update(device_token=…, webapp_id=…)` in the
  toolkit, or `{"aps": {"content-available": 1}, "webapp_id": "…",
"approvals_refresh": true}`, reloads immediately, e.g. when a new request
  comes in. For a visible notification ("New vacation request from Anna"),
  also send a normal push.
- **JS bridge**: `await BMSNative.call('refreshApprovals')` after your
  web page has approved something itself.

## With the toolkit

```python
from bmsdna.app_native import (
    Approval,
    ApprovalDecisionResult,
    ApprovalDetail,
    create_approvals_router,
)


async def get_approvals(context):
    rows = await my_repo.open_requests_for(context.user["email"])
    return [
        Approval(
            id=str(r["id"]),
            title="Vacation request",
            subtitle=f"{r['name']} · {r['period']}",
            amount=f"{r['days']} days",
            due_at=r["due_at"],
            details=[ApprovalDetail(label="Deputy", value=r["deputy"])],
            reject_comment="required",
        )
        for r in rows
    ]


async def on_decision(body, context):
    if not await my_repo.may_decide(body.approval_id, context.user["email"]):
        return ApprovalDecisionResult(ok=False, message="Not (or no longer) yours to decide")
    await my_repo.decide(body.approval_id, body.decision, body.comment, context.user["email"])
    return None  # plain "ok", the app removes the approval


app.include_router(
    create_approvals_router(
        get_approvals=get_approvals,
        on_decision=on_decision,
        auth_dependency=require_user,  # your own login check
    ),
    prefix="/api",
)
```

## Trying it out

You can check the format without the app: mount `create_approvals_router()` locally
and call `GET api/approvals?device_id=…` or
`POST api/approval-decisions` with `curl`.
