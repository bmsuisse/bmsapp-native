"""Native forms and content (`showForm`, `showContent`) with the built npm
package in a real browser against the Python models.

The page's fake bridge plays the native sheets (see page/index.html): the test
scripts what "the user" does, the fake uploads media to the real document
router, calls `window.onNativeSurfaceAction` for a round trip and takes the
page's `surfaceResult`. The harness validates every definition with
`NativeForm` / `NativeContent`, like the app parses it. The real iOS app does
not take part.
"""

import re
from typing import Any

from helpers import open_page
from playwright.sync_api import Page

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# What a web app does with a submitted form: send the values and the media
# references to its own backend (the app attaches the token to this itself).
POST_CUSTOMER = """async (values) => {
  const response = await fetch('/api/customers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: 'e2e-device', ...values }),
  })
  return { status: response.status, body: await response.json() }
}"""


def _open(page: Page, path: str = "/") -> Page:
    """The test page, with `window.postCustomer` for what a web app does after a form."""
    open_page(page, path)
    page.evaluate("window.postCustomer = " + POST_CUSTOMER)
    return page


def _log(page: Page) -> list[dict[str, Any]]:
    return page.request.get("/native-log").json()


def _results(page: Page) -> list[dict[str, Any]]:
    """What the page answered to the app with `surfaceResult`."""
    return [m for m in _log(page) if m["action"] == "surfaceResult"]


def _backend(page: Page) -> dict[str, list[dict[str, Any]]]:
    return page.request.get("/backend-log").json()


def _script(page: Page, *behaviors: dict[str, Any]) -> None:
    """What the user does with the next surfaces."""
    page.evaluate("(b) => window.__surfaces.script.push(...b)", list(behaviors))


def test_show_form_returns_values_and_labels(page: Page) -> None:
    _open(page)
    _script(
        page,
        {
            "submit": [
                {
                    "values": {"name": "Miller Ltd", "seats": 3, "vip": True, "owner": "u-1"},
                    "labels": {"owner": "Anna Muster"},
                }
            ]
        },
    )

    result = page.evaluate(
        """() => window.native.showForm({
          id: 'new-customer',
          title: 'New customer',
          size: 'fit',
          context: { source: 'customer-list' },
          fields: [
            { id: 'name', type: 'text', required: true, maxLength: 80 },
            { id: 'seats', type: 'stepper', min: 1, max: 20 },
            { id: 'vip', type: 'toggle' },
            { id: 'owner', type: 'search', minQueryLength: 2 },
          ],
        })"""
    )

    assert result == {
        "ok": True,
        "id": "new-customer",
        "action": "submit",
        "values": {"name": "Miller Ltd", "seats": 3, "vip": True, "owner": "u-1"},
        "labels": {"owner": "Anna Muster"},
        "context": {"source": "customer-list"},
    }
    [shown] = _log(page)
    assert shown["action"] == "showForm"
    assert shown["size"] == "fit"
    assert shown["fields"][1] == {"id": "seats", "type": "stepper", "min": 1, "max": 20}


def test_an_invalid_definition_is_refused_like_the_app_does(page: Page) -> None:
    _open(page)
    result = page.evaluate(
        """async () => ({
          form: await window.native.showForm({ fields: [{ id: 'a' }, { id: 'a' }] }),
          content: await window.native.showContent({ blocks: [{ type: 'image' }] }),
          big: await window.native.showForm({
            fields: [{ id: 'card', type: 'photo', max: 11 }],
          }),
          empty: await window.native.showContent({ blocks: [] }),
        })"""
    )

    for name in ("form", "content", "big", "empty"):
        assert result[name]["ok"] is False
        assert result[name]["error"] == "invalid"
    assert "unique" in result["form"]["message"]
    assert "url" in result["content"]["message"]
    assert result["big"]["message"].startswith("fields.0")


def test_round_trip_with_a_field_error_and_then_success(page: Page) -> None:
    _open(page)
    _script(
        page,
        {
            "submit": [
                {"values": {"name": "Miller Ltd", "email": "taken@example.com"}},
                {"values": {"name": "Miller Ltd", "email": "new@example.com"}},
            ]
        },
    )

    result = page.evaluate(
        """async () => {
          const statuses = []
          const res = await window.native.showForm(
            {
              id: 'new-customer',
              fields: [{ id: 'name' }, { id: 'email', type: 'email' }],
            },
            {
              onSubmit: async (values) => {
                const answer = await window.postCustomer(values)
                statuses.push(answer.status)
                if (answer.status === 422) return { fieldErrors: answer.body.detail.fieldErrors }
              },
            }
          )
          return { res, statuses }
        }"""
    )

    assert result["statuses"] == [422, 200]
    assert result["res"]["ok"] is True
    assert result["res"]["values"]["email"] == "new@example.com"
    # The form went to the app with `wait`, and the page answered twice.
    assert next(m for m in _log(page) if m["action"] == "showForm")["submit"] == {"wait": True}
    assert _results(page) == [
        {
            "action": "surfaceResult",
            "id": "new-customer",
            "ok": False,
            "fieldErrors": {"email": "Already registered"},
        },
        {"action": "surfaceResult", "id": "new-customer", "ok": True},
    ]

    # The handler is gone once the promise settled: a stray callback is not answered.
    page.evaluate(
        "() => window.onNativeSurfaceAction({ id: 'new-customer', action: 'submit', values: {} })"
    )
    page.wait_for_timeout(100)
    assert len(_results(page)) == 2


def test_a_thrown_error_keeps_the_form_open(page: Page) -> None:
    _open(page)
    _script(page, {"submit": [{"values": {"name": "first"}}, {"values": {"name": "second"}}]})

    result = page.evaluate(
        """async () => {
          let attempts = 0
          const res = await window.native.showForm(
            { id: 'new-customer', fields: [{ id: 'name' }] },
            {
              onSubmit: async () => {
                attempts += 1
                if (attempts === 1) throw new Error('The service is not reachable.')
              },
            }
          )
          return { res, attempts }
        }"""
    )

    assert result["attempts"] == 2
    assert result["res"]["values"] == {"name": "second"}
    assert _results(page) == [
        {
            "action": "surfaceResult",
            "id": "new-customer",
            "ok": False,
            "message": "The service is not reachable.",
        },
        {"action": "surfaceResult", "id": "new-customer", "ok": True},
    ]


def test_fallback_to_the_web_ui_without_the_capability(page: Page) -> None:
    _open(page, "/?capabilities=customChrome")
    result = page.evaluate(
        """async () => {
          const n = window.native
          // What a web app does: native form if possible, otherwise its own web form.
          const openCustomerForm = async () => {
            if (n.canShowNativeForms()) {
              const res = await n.showForm({ fields: [{ id: 'name' }] })
              if (!n.isNativeSurfaceUnsupported(res)) return 'native'
            }
            document.body.innerHTML = '<form id="web-form"><input name="name"></form>'
            return 'web'
          }
          const direct = await n.showForm({ fields: [{ id: 'name' }] })
          const content = await n.showContent({ blocks: [{ type: 'divider' }] })
          return {
            forms: n.canShowNativeForms(),
            content: n.canShowNativeContent(),
            direct,
            contentError: content.error,
            unsupported: n.isNativeSurfaceUnsupported(direct),
            used: await openCustomerForm(),
          }
        }"""
    )

    assert result["forms"] is False
    assert result["content"] is False
    assert result["direct"]["error"] == "capability"
    assert result["contentError"] == "capability"
    assert result["unsupported"] is True
    assert result["used"] == "web"
    assert page.locator("form#web-form").count() == 1


def test_only_the_granted_surface_capability_is_usable(page: Page) -> None:
    _open(page, "/?capabilities=nativeContent")
    _script(page, {"dismiss": True})
    result = page.evaluate(
        """async () => ({
          forms: window.native.canShowNativeForms(),
          content: window.native.canShowNativeContent(),
          form: await window.native.showForm({ fields: [{ id: 'a' }] }),
          shown: await window.native.showContent({ id: 'info', blocks: [{ type: 'divider' }] }),
          closed: await window.native.closeSurface(),
        })"""
    )

    assert (result["forms"], result["content"]) == (False, True)
    assert result["form"]["error"] == "capability"
    assert result["shown"] == {"ok": True, "id": "info", "action": "dismiss"}
    assert result["closed"] == {"ok": True}


def test_fallback_in_a_browser_without_the_app(page: Page) -> None:
    _open(page, "/?browser=1")
    result = page.evaluate(
        """async () => {
          const res = await window.native.showForm({ fields: [{ id: 'a' }] })
          return {
            forms: window.native.canShowNativeForms(),
            content: window.native.canShowNativeContent(),
            res,
            withHandler: await window.native.showForm({ fields: [{ id: 'a' }] }, { onSubmit() {} }),
            shown: await window.native.showContent({ blocks: [{ type: 'divider' }] }),
            closed: await window.native.closeSurface(),
            unsupported: window.native.isNativeSurfaceUnsupported(res),
          }
        }"""
    )

    unavailable = {"ok": False, "error": "unavailable"}
    assert result == {
        "forms": False,
        "content": False,
        "res": unavailable,
        "withHandler": unavailable,
        "shown": unavailable,
        "closed": unavailable,
        "unsupported": True,
    }
    assert _log(page) == []


def test_an_older_app_answers_unknown_action(page: Page) -> None:
    _open(page)
    _script(page, {"error": "unknownAction"}, {"error": "unknownAction"})
    result = page.evaluate(
        """async () => {
          const form = await window.native.showForm({ fields: [{ id: 'a' }] })
          const content = await window.native.showContent({ blocks: [{ type: 'divider' }] })
          return {
            form,
            content,
            unsupported: [form, content].map((r) => window.native.isNativeSurfaceUnsupported(r)),
          }
        }"""
    )

    assert result["form"] == {"ok": False, "error": "unknownAction"}
    assert result["content"] == {"ok": False, "error": "unknownAction"}
    assert result["unsupported"] == [True, True]


def test_cancelled_busy_and_close_surface(page: Page) -> None:
    _open(page)
    _script(page, {"dismiss": True}, {"hold": True})

    result = page.evaluate(
        """async () => {
          const dismissed = await window.native.showForm({ fields: [{ id: 'a' }] })
          // Stays open until closeSurface: the next call finds it busy.
          const pending = window.native.showForm({ id: 'open-one', fields: [{ id: 'a' }] })
          while (!window.__surfaces.open) await new Promise((r) => setTimeout(r, 5))
          const second = await window.native.showForm({ fields: [{ id: 'b' }] })
          const closed = await window.native.closeSurface({ id: 'open-one' })
          return {
            dismissed,
            second,
            closed,
            pending: await pending,
            unsupported: [dismissed, second].map(
              (r) => window.native.isNativeSurfaceUnsupported(r)
            ),
          }
        }"""
    )

    assert result["dismissed"] == {"ok": False, "error": "cancelled"}
    assert result["second"]["error"] == "busy"
    assert result["closed"] == {"ok": True}
    assert result["pending"] == {"ok": False, "error": "cancelled"}
    # An answer, not a missing feature: the page must not fall back to its web UI.
    assert result["unsupported"] == [False, False]


def test_chained_flow_from_a_content_action(page: Page) -> None:
    _open(page)
    _script(page, {"action": "edit"}, {"submit": [{"values": {"reason": "Moved"}}]})

    result = page.evaluate(
        """() => window.native.showContent({
          id: 'customer-123',
          title: 'Miller Ltd',
          blocks: [{ type: 'text', markdown: 'Customer **123**' }],
          actions: [
            {
              id: 'edit',
              label: 'Edit',
              then: [
                {
                  showForm: {
                    id: 'edit-customer',
                    fields: [{ id: 'reason', type: 'textarea' }],
                  },
                },
              ],
            },
          ],
        })"""
    )

    assert result == {
        "ok": True,
        "id": "customer-123",
        "action": "edit",
        "next": {
            "ok": True,
            "id": "edit-customer",
            "action": "submit",
            "values": {"reason": "Moved"},
            "labels": {},
        },
    }


def test_chained_flow_from_the_answer_of_the_page(page: Page) -> None:
    _open(page)
    _script(page, {"submit": [{"values": {"name": "Miller Ltd"}}]}, {"action": "done"})

    result = page.evaluate(
        """() => window.native.showForm(
          { id: 'new-customer', fields: [{ id: 'name' }] },
          {
            // The page created the customer and shows what was created.
            onSubmit: async () => ({
              then: [
                {
                  showContent: {
                    id: 'created',
                    title: 'Customer created',
                    size: 'fit',
                    blocks: [
                      { type: 'callout', style: 'success', text: 'Miller Ltd was created.' },
                    ],
                    actions: [{ id: 'done', label: 'Done', style: 'primary' }],
                  },
                },
              ],
            }),
          }
        )"""
    )

    assert result["ok"] is True
    assert result["next"] == {"ok": True, "id": "created", "action": "done"}
    [answer] = _results(page)
    assert answer["ok"] is True
    assert answer["then"][0]["showContent"]["id"] == "created"


def test_content_action_round_trip(page: Page) -> None:
    _open(page)
    _script(page, {"action": "approve", "values": {"comment": "ok"}})

    result = page.evaluate(
        """async () => {
          const seen = []
          const res = await window.native.showContent(
            {
              id: 'order-1',
              blocks: [{ type: 'fields', fields: [{ id: 'comment', type: 'textarea' }] }],
              actions: [
                { id: 'approve', label: 'Approve', submit: true },
                { id: 'open', label: 'Open', then: [{ openPath: '/orders/1' }] },
              ],
            },
            {
              onAction: async (event) => {
                seen.push([event.action, event.values])
                return { message: 'Approved' }
              },
            }
          )
          return { res, seen }
        }"""
    )

    assert result["seen"] == [["approve", {"comment": "ok"}]]
    assert result["res"]["action"] == "approve"
    shown = next(m for m in _log(page) if m["action"] == "showContent")
    # Only the action without `then` waits for the page.
    assert [(a["id"], a.get("wait")) for a in shown["actions"]] == [
        ("approve", True),
        ("open", None),
    ]
    assert _results(page) == [
        {"action": "surfaceResult", "id": "order-1", "ok": True, "message": "Approved"}
    ]


def test_photos_are_uploaded_by_the_app_and_the_page_gets_references(page: Page) -> None:
    _open(page)
    _script(
        page,
        {
            "submit": [
                {
                    "values": {"name": "Miller Ltd"},
                    "uploads": [
                        {
                            "key": "card",
                            "field": "card",
                            "name": "card.jpg",
                            "mime": "image/jpeg",
                            "content": "JPEGDATA",
                        }
                    ],
                }
            ]
        },
    )

    result = page.evaluate(
        """async () => {
          const res = await window.native.showForm({
            id: 'new-customer',
            context: { source: 'customer-list' },
            fields: [{ id: 'name' }, { id: 'card', type: 'photo', max: 1 }],
          })
          const sent = await window.postCustomer({
            name: res.values.name,
            card: res.values.card,
          })
          return { res, sent }
        }"""
    )

    # The router answered with an id: that is the reference.
    assert result["res"]["values"]["card"] == [
        {"name": "card.jpg", "mime": "image/jpeg", "size": 8, "ref": "doc-1"}
    ]
    assert result["sent"] == {
        "status": 200,
        "body": {
            "ok": True,
            "id": "c-1",
            "files": [{"name": "card.jpg", "size": 8, "contentType": "image/jpeg"}],
        },
    }
    [upload] = _backend(page)["uploads"]
    assert UUID.match(upload.pop("upload_id"))
    assert upload == {
        "device_id": "e2e-device",
        "user_email": "anna@example.com",
        "kind": "form",
        "form_id": "new-customer",
        "field_id": "card",
        "context": {"source": "customer-list"},
        "filename": "card.jpg",
        "content_type": "image/jpeg",
        "size": 8,
    }


def test_without_an_id_from_the_router_the_reference_is_the_upload_id(page: Page) -> None:
    _open(page)  # resets the harness, so set the mode afterwards
    page.request.post("/test/document-reference", data={"mode": "none"})
    _script(
        page,
        {
            "submit": [
                {
                    "values": {"name": "Miller Ltd"},
                    "uploads": [
                        {
                            "key": "contract",
                            "field": "contract",
                            "name": "contract.pdf",
                            "mime": "application/pdf",
                            "content": "%PDF-1.7",
                        }
                    ],
                }
            ]
        },
    )

    result = page.evaluate(
        """async () => {
          const res = await window.native.showForm({
            id: 'new-customer',
            fields: [{ id: 'name' }, { id: 'contract', type: 'scan', format: 'pdf' }],
          })
          const sent = await window.postCustomer({
            name: res.values.name,
            card: res.values.contract,
          })
          return { res, sent }
        }"""
    )

    [upload] = _backend(page)["uploads"]
    [ref] = result["res"]["values"]["contract"]
    assert ref["ref"] == upload["upload_id"]
    assert UUID.match(ref["ref"])
    assert result["sent"]["status"] == 200  # the backend finds the file under the upload_id
    assert result["sent"]["body"]["files"][0]["name"] == "contract.pdf"


def test_the_same_upload_twice_is_one_file(page: Page) -> None:
    _open(page)
    _script(
        page,
        {
            "submit": [
                {
                    "values": {},
                    "uploads": [
                        {
                            "key": "signature",
                            "field": "signature",
                            "name": "signature.png",
                            "mime": "image/png",
                            "content": "PNG",
                            "times": 2,  # the app retried after a failed attempt
                        }
                    ],
                }
            ]
        },
    )

    result = page.evaluate(
        """async () => {
          const res = await window.native.showForm({
            id: 'sign-here',
            fields: [{ id: 'signature', type: 'signature' }],
          })
          const sent = await window.postCustomer({
            name: 'x',
            card: res.values.signature,
          })
          return { res, sent }
        }"""
    )

    uploads = _backend(page)["uploads"]
    assert len(uploads) == 2
    assert uploads[0]["upload_id"] == uploads[1]["upload_id"]
    assert len(result["res"]["values"]["signature"]) == 1
    assert result["res"]["values"]["signature"][0]["ref"] == "doc-1"
    assert len(result["sent"]["body"]["files"]) == 1


def test_an_unknown_reference_is_422_and_names_it(page: Page) -> None:
    _open(page)
    results = page.evaluate(
        """async () => {
          const send = window.postCustomer
          const ref = { name: 'a.jpg', mime: 'image/jpeg', size: 1, ref: 'expired' }
          return {
            unknown: await send({ name: 'x', card: [ref] }),
            notAFileRef: await send({ name: 'x', card: [{ ref: '' }] }),
          }
        }"""
    )

    assert results["unknown"]["status"] == 422
    assert results["unknown"]["body"]["detail"] == {
        "message": "Unknown or expired upload reference",
        "refs": ["expired"],
    }
    assert results["notAFileRef"]["status"] == 422


def test_option_lookups_of_a_native_form_carry_form_id_and_context(page: Page) -> None:
    _open(page)
    _script(
        page,
        {
            "submit": [
                {
                    "values": {"owner": "u-1"},
                    "lookups": [{"field": "owner", "query": "an"}],
                }
            ]
        },
    )

    page.evaluate(
        """() => window.native.showForm({
          id: 'new-customer',
          context: { source: 'customer-list' },
          fields: [{ id: 'owner', type: 'search', minQueryLength: 2 }],
        })"""
    )

    [request] = _backend(page)["options"]
    assert request["form_id"] == "new-customer"
    assert request["widget_id"] is None
    assert request["field_id"] == "owner"
    assert request["query"] == "an"
    assert request["context"] == {"source": "customer-list"}
    assert request["values"] == {"owner": "u-1"}
    [answer] = page.evaluate("() => window.__surfaces.lookups")
    assert answer == {
        "status": 200,
        "body": {"options": [{"value": "u-1", "label": "Anna Muster"}]},
    }


def test_limit_warnings_reach_the_console_and_the_call_goes_through(page: Page) -> None:
    _open(page)
    warnings: list[str] = []
    page.on("console", lambda m: warnings.append(m.text) if m.type == "warning" else None)
    _script(page, {"dismiss": True})

    result = page.evaluate(
        """() => window.native.showForm({
          fields: Array.from({ length: 61 }, (_, i) => ({ id: 'f' + i })),
        })"""
    )

    # The harness (like the app) refuses the oversized definition; the page was
    # warned first, before the call.
    assert result["ok"] is False
    assert result["error"] == "invalid"
    assert any("[@bmsuisse/app-native] showForm: 61 fields" in w for w in warnings)


def test_the_app_sends_labels_with_the_values_of_a_round_trip(page: Page) -> None:
    _open(page)
    _script(
        page,
        {
            "submit": [
                {
                    "values": {"owner": "u-1", "name": "Miller Ltd"},
                    "labels": {"owner": "Anna Muster"},
                }
            ]
        },
    )

    seen = page.evaluate(
        """async () => {
          let seen
          await window.native.showForm(
            {
              id: 'new-customer',
              fields: [{ id: 'name' }, { id: 'owner', type: 'search' }],
            },
            { onSubmit: (values, event) => { seen = { values, labels: event.labels } } }
          )
          return seen
        }"""
    )

    assert seen == {
        "values": {"owner": "u-1", "name": "Miller Ltd"},
        "labels": {"owner": "Anna Muster"},
    }


def test_a_chained_surface_with_its_own_round_trip_is_answered_by_id(page: Page) -> None:
    _open(page)
    _script(
        page,
        {"action": "reject"},
        {"submit": [{"values": {"reason": "Too expensive"}}]},
    )

    result = page.evaluate(
        """async () => {
          const reasons = []
          const off = window.native.onSurfaceAction('reject-reason', async ({ values }) => {
            reasons.push(values.reason)
            return { message: 'Rejected' }
          })
          try {
            // The root has no round trip of its own. The chained form has an
            // explicit id and switches its round trip on itself.
            const res = await window.native.showContent({
              id: 'order-1',
              blocks: [{ type: 'text', markdown: 'Order **1**' }],
              actions: [
                {
                  id: 'reject',
                  label: 'Reject',
                  style: 'destructive',
                  then: [
                    {
                      showForm: {
                        id: 'reject-reason',
                        submit: { wait: true },
                        fields: [{ id: 'reason', type: 'textarea', required: true }],
                      },
                    },
                  ],
                },
              ],
            })
            return { res, reasons }
          } finally {
            off()
          }
        }"""
    )

    assert result["reasons"] == ["Too expensive"]
    assert result["res"]["action"] == "reject"
    assert result["res"]["next"]["id"] == "reject-reason"
    assert result["res"]["next"]["values"] == {"reason": "Too expensive"}
    assert _results(page) == [
        {"action": "surfaceResult", "id": "reject-reason", "ok": True, "message": "Rejected"}
    ]
