"""Documents with the built npm package in a real browser: `scanDocument` with
options, `pickFiles`, files shared into the web app, `previewFile`.

The scanner, picker and Share Extension are played by the page's fake bridge
(`window.__docs`, `window.__share`); it uploads to the real document router
(`create_document_router`) with the fields of the contract and retries once after
a network error or a 5xx. The real iOS app does not take part.
"""

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from helpers import open_page
from playwright.sync_api import Page

FIXTURES = Path(__file__).resolve().parent.parent / "contract-fixtures"
FEATURE_OF = {
    "scanDocument": "scanOptions",
    "pickFiles": "pickFiles",
    "dictate": "dictate",
    "previewFile": "previewFile",
    "getAccessToken": "tokenResources",
}


def _log(page: Page) -> list[dict]:
    return page.request.get("/native-log").json()


def _uploads(page: Page) -> list[dict]:
    return page.request.get("/backend-log").json()["uploads"]


def _script(page: Page, *steps: dict) -> None:
    page.evaluate("(steps) => window.__docs.script.push(...steps)", list(steps))


def _backend(page: Page, **settings: Any) -> None:
    page.request.post("/test/document-backend", data=settings)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# --- scanDocument -----------------------------------------------------------------


def test_scan_document_without_options_uploads_as_before_and_returns_the_documents(
    page: Page,
) -> None:
    open_page(page)
    _script(page, {"documents": [{"name": "scan.pdf", "pages": 3, "content": "PDF"}]})
    res = page.evaluate("() => window.native.scanDocument()")

    assert res["ok"] is True
    [doc] = res["documents"]
    assert doc["name"] == "scan.pdf" and doc["pages"] == 3 and doc["size"] == 3
    assert doc["upload"] == {"status": 200, "body": {"ok": True, "id": "doc-1"}}
    assert _log(page) == [{"action": "scanDocument"}]
    [upload] = _uploads(page)
    assert (upload["kind"], upload["context"]) == ("scan", None)
    assert upload["upload_id"] == doc["uploadId"]
    assert (upload["filename"], upload["size"]) == ("scan.pdf", 3)


def test_scan_document_options_reach_the_app_and_the_upload(page: Page) -> None:
    open_page(page)
    _script(page, {"documents": [{"name": "a.pdf"}, {"name": "b.pdf"}, {"name": "c.pdf"}]})
    res = page.evaluate(
        """() => window.native.scanDocument({
          kind: 'supplier-offer', multiple: true, context: { offerId: 'O-1' },
        })"""
    )

    assert [d["name"] for d in res["documents"]] == ["a.pdf", "b.pdf", "c.pdf"]
    assert _log(page) == [
        {
            "action": "scanDocument",
            "kind": "supplier-offer",
            "multiple": True,
            "context": {"offerId": "O-1"},
        }
    ]
    uploads = _uploads(page)
    assert {u["kind"] for u in uploads} == {"supplier-offer"}
    assert {json.dumps(u["context"]) for u in uploads} == {'{"offerId": "O-1"}'}
    # Separate PDFs, separate uploads, separate upload ids.
    assert len({u["upload_id"] for u in uploads}) == 3
    assert [d["upload"]["body"]["id"] for d in res["documents"]] == ["doc-1", "doc-2", "doc-3"]


def test_scan_document_scans_one_document_without_multiple(page: Page) -> None:
    open_page(page)
    _script(page, {"documents": [{"name": "a.pdf"}, {"name": "b.pdf"}]})
    res = page.evaluate("() => window.native.scanDocument({ kind: 'offer' })")
    assert [d["name"] for d in res["documents"]] == ["a.pdf"]


def test_scan_document_in_return_mode_brings_the_pdf_back_as_base64(page: Page) -> None:
    open_page(page)
    _script(page, {"documents": [{"name": "a.pdf", "content": "%PDF hello", "pages": 2}]})
    res = page.evaluate("() => window.native.scanDocument({ mode: 'return' })")

    [doc] = res["documents"]
    assert base64.b64decode(doc["data"]) == b"%PDF hello"
    assert "upload" not in doc
    assert _uploads(page) == []


def test_scan_document_cancel_before_and_after_the_first_document(page: Page) -> None:
    open_page(page)
    before = page.evaluate("() => window.native.scanDocument({ multiple: true })")
    assert before == {"ok": False, "error": "cancelled"}

    # The user finished one document, chose "Next document" and cancelled.
    _script(page, {"documents": [{"name": "done.pdf"}]})
    after = page.evaluate("() => window.native.scanDocument({ multiple: true })")
    assert after["ok"] is True and [d["name"] for d in after["documents"]] == ["done.pdf"]


def test_scan_document_per_document_failures_do_not_fail_the_batch(page: Page) -> None:
    open_page(page)
    _script(
        page,
        {
            "documents": [
                {"name": "ok.pdf"},
                {"name": "bad.pdf", "fail": True},
                {"name": "huge.pdf", "tooLarge": True},
            ]
        },
    )
    res = page.evaluate("() => window.native.scanDocument({ multiple: true, mode: 'return' })")

    ok, bad, huge = res["documents"]
    assert "error" not in ok
    assert bad["error"] == "failed" and set(bad) == {"name", "uploadId", "error"}
    assert huge["error"] == "tooLarge" and huge["size"] > 25_000_000


def test_scan_document_errors_reach_the_page(page: Page) -> None:
    open_page(page, "/?capabilities=deviceApps")
    assert page.evaluate("() => window.native.scanDocument()")["error"] == "capability"
    open_page(page)
    _script(page, {"error": "unavailable"})
    assert page.evaluate("() => window.native.scanDocument()")["error"] == "unavailable"


# --- retry and idempotency ----------------------------------------------------------


def test_the_app_retries_once_after_a_5xx_with_the_same_upload_id(page: Page) -> None:
    open_page(page)
    _backend(page, failures={"flaky.pdf": 1})
    _script(page, {"documents": [{"name": "flaky.pdf"}]})
    res = page.evaluate("() => window.native.scanDocument()")

    [doc] = res["documents"]
    assert doc["upload"]["status"] == 200 and "error" not in doc
    attempts = _uploads(page)
    assert [a.get("failed", False) for a in attempts] == [True, False]
    assert attempts[0]["upload_id"] == attempts[1]["upload_id"] == doc["uploadId"]


def test_a_second_5xx_is_the_final_status_and_the_body_is_passed_verbatim(page: Page) -> None:
    open_page(page)
    _backend(page, failures={"down.pdf": 2})
    _script(page, {"documents": [{"name": "down.pdf"}]})
    res = page.evaluate("() => window.native.scanDocument({ multiple: true })")

    [doc] = res["documents"]
    assert doc["error"] == "failed"
    assert doc["upload"] == {"status": 503, "body": {"detail": "Try again"}}
    assert len(_uploads(page)) == 2


def test_a_lost_response_runs_the_callback_twice_without_the_store(page: Page) -> None:
    open_page(page)
    _script(page, {"documents": [{"name": "a.pdf", "dropResponse": True}]})
    page.evaluate("() => window.native.scanDocument()")
    first, second = _uploads(page)
    assert first["upload_id"] == second["upload_id"]


def test_a_lost_response_is_answered_from_the_store_on_the_retry(page: Page) -> None:
    open_page(page)
    _backend(page, dedupe=True)
    _script(page, {"documents": [{"name": "a.pdf", "dropResponse": True}]})
    res = page.evaluate("() => window.native.scanDocument()")

    [doc] = res["documents"]
    assert doc["upload"]["body"] == {"ok": True, "id": "doc-1"}
    assert len(_uploads(page)) == 1  # the callback ran once


# --- old apps -------------------------------------------------------------------------


def test_an_old_app_scans_as_before_and_options_are_unavailable(page: Page) -> None:
    open_page(page, "/?oldApp")
    assert page.evaluate("() => window.native.hasFeature('scanResult')") is False
    _script(page, {"documents": [{"name": "a.pdf"}]})
    plain = page.evaluate("() => window.native.scanDocument()")
    assert plain == {"ok": True, "documents": [], "oldApp": True}
    assert [u["kind"] for u in _uploads(page)] == ["scan"]

    # Options would be ignored by that app: nothing is asked, nothing is scanned.
    page.request.delete("/native-log")
    res = page.evaluate("() => window.native.scanDocument({ mode: 'return', multiple: true })")
    assert res["error"] == "unavailable"
    assert _log(page) == []


def test_an_app_with_the_result_but_without_the_options(page: Page) -> None:
    open_page(page, "/?features=scanResult")
    res = page.evaluate("() => window.native.scanDocument({ kind: 'offer' })")
    assert res["error"] == "unavailable"
    _script(page, {"documents": [{"name": "a.pdf"}]})
    plain = page.evaluate("() => window.native.scanDocument()")
    assert plain["ok"] is True and len(plain["documents"]) == 1


# --- pickFiles --------------------------------------------------------------------------


def test_pick_files_returns_base64_by_default(page: Page) -> None:
    open_page(page)
    _script(
        page,
        {"documents": [{"name": "offer.eml", "mime": "message/rfc822", "content": "Subject: x"}]},
    )
    res = page.evaluate(
        """() => window.native.pickFiles({
          sources: ['files', 'photos'], accept: ['application/pdf', '.eml'],
        })"""
    )

    [doc] = res["documents"]
    assert doc["mime"] == "message/rfc822"
    assert base64.b64decode(doc["data"]) == b"Subject: x"
    assert _log(page) == [
        {
            "action": "pickFiles",
            "sources": ["files", "photos"],
            "accept": ["application/pdf", ".eml"],
        }
    ]
    assert _uploads(page) == []


def test_pick_files_can_upload_with_kind_and_context(page: Page) -> None:
    open_page(page)
    _script(page, {"documents": [{"name": "a.pdf"}, {"name": "b.pdf"}]})
    res = page.evaluate(
        """() => window.native.pickFiles({
          sources: ['files'], mode: 'upload', multiple: true, context: { offerId: 'O-1' },
        })"""
    )

    assert [d["upload"]["body"]["id"] for d in res["documents"]] == ["doc-1", "doc-2"]
    uploads = _uploads(page)
    assert {u["kind"] for u in uploads} == {"pick"}  # the default kind
    assert {json.dumps(u["context"]) for u in uploads} == {'{"offerId": "O-1"}'}


def test_pick_files_takes_one_file_without_multiple_and_photos_arrive_as_jpeg(page: Page) -> None:
    open_page(page)
    _script(
        page,
        {"documents": [{"name": "IMG.heic", "mime": "image/heic", "photo": True}, {"name": "b"}]},
    )
    res = page.evaluate("() => window.native.pickFiles({ sources: ['photos'] })")
    [doc] = res["documents"]
    assert doc["mime"] == "image/jpeg"


def test_pick_files_with_the_camera_needs_the_capability(page: Page) -> None:
    open_page(page, "/?capabilities=deviceApps")
    res = page.evaluate("() => window.native.pickFiles({ sources: ['files', 'camera'] })")
    assert res["error"] == "capability"
    _script(page, {"documents": [{"name": "a.pdf"}]})
    files = page.evaluate("() => window.native.pickFiles({ sources: ['files'] })")
    assert files["ok"] is True  # files need no capability


def test_pick_files_cancelled(page: Page) -> None:
    open_page(page)
    assert page.evaluate("() => window.native.pickFiles({ sources: ['files'] })") == {
        "ok": False,
        "error": "cancelled",
    }


def test_pick_files_in_an_old_app_is_unavailable_without_asking(page: Page) -> None:
    open_page(page, "/?oldApp")
    res = page.evaluate("() => window.native.pickFiles({ sources: ['files'] })")
    assert res == {"ok": False, "error": "unavailable"}
    assert _log(page) == []
    # The old app answers unknownAction when asked directly.
    raw = page.evaluate("() => window.native.call('pickFiles', { sources: ['files'] })")
    assert raw == {"ok": False, "error": "unknownAction"}


def test_pick_files_in_the_browser_uses_a_file_input(page: Page, tmp_path: Path) -> None:
    open_page(page, "/?browser")
    pdf = tmp_path / "offer.pdf"
    pdf.write_bytes(b"%PDF-1.4 offer")
    mail = tmp_path / "offer.eml"
    mail.write_text("Subject: x")

    with page.expect_file_chooser() as chooser:
        page.evaluate(
            """() => {
              window.__picked = window.native.pickFiles({
                sources: ['files'], accept: ['.pdf', '.eml'], multiple: true,
              })
            }"""
        )
    assert chooser.value.is_multiple
    chooser.value.set_files([pdf, mail])
    res = page.evaluate("() => window.__picked")

    assert res["ok"] is True
    first, second = res["documents"]
    assert (first["name"], first["mime"], first["size"]) == ("offer.pdf", "application/pdf", 14)
    assert base64.b64decode(first["data"]) == b"%PDF-1.4 offer"
    assert second["name"] == "offer.eml"
    assert first["uploadId"] != second["uploadId"]
    assert page.locator("input[type=file]").count() == 0  # cleaned up


def test_pick_files_in_the_browser_has_no_upload_mode_and_no_app_calls(page: Page) -> None:
    open_page(page, "/?browser")
    res = page.evaluate(
        """async () => ({
          upload: await window.native.pickFiles({ sources: ['files'], mode: 'upload' }),
          bad: await window.native.pickFiles({ sources: [] }),
        })"""
    )
    assert res["upload"] == {"ok": False, "error": "unavailable"}
    assert res["bad"]["error"] == "invalid"
    assert _log(page) == []


# --- receiveDocuments -------------------------------------------------------------


def test_a_shared_batch_is_delivered_once_to_the_registered_handler(page: Page) -> None:
    open_page(page)
    page.evaluate(
        """() => {
          window.__got = []
          window.__off = window.native.onDocumentsReceived((e) => window.__got.push(e))
        }"""
    )
    outcome = page.evaluate(
        """() => window.__share([
          { name: 'Offer.pdf' }, { name: 'Mail.eml', mime: 'message/rfc822' },
        ])"""
    )

    assert outcome == "delivered"
    [batch] = page.evaluate("() => window.__got")
    assert [d["name"] for d in batch["documents"]] == ["Offer.pdf", "Mail.eml"]
    assert batch["documents"][0]["upload"]["body"] == {"ok": True, "id": "doc-1"}
    assert [(u["kind"], u["context"]) for u in _uploads(page)] == [("shared", None)] * 2
    assert page.evaluate("() => window.__docs.queue.length") == 0


def test_a_batch_shared_before_the_page_listens_is_queued_and_handed_over_once(page: Page) -> None:
    open_page(page)
    assert page.evaluate("() => window.__share([{ name: 'Offer.pdf' }])") == "queued"

    page.evaluate(
        """() => {
          window.__got = []
          window.__off = window.native.onDocumentsReceived((e) => window.__got.push(e))
        }"""
    )
    page.wait_for_function("() => window.__got.length === 1")
    assert page.evaluate("() => window.__got[0].documents.map((d) => d.name)") == ["Offer.pdf"]
    assert page.evaluate("() => window.__docs.queue.length") == 0

    # A second listener finds nothing queued: exactly once.
    page.evaluate(
        """async () => {
          window.__second = []
          window.native.onDocumentsReceived((e) => window.__second.push(e))
          await new Promise((r) => setTimeout(r, 100))
        }"""
    )
    assert page.evaluate("() => window.__second.length") == 0
    consumed = [m for m in _log(page) if m["action"] == "consumeReceivedDocuments"]
    assert len(consumed) == 2  # one per onDocumentsReceived call


def test_after_the_last_handler_is_removed_the_app_queues_again(page: Page) -> None:
    open_page(page)
    page.evaluate("() => { window.__off = window.native.onDocumentsReceived(() => {}) }")
    assert page.evaluate("() => typeof window.onNativeDocumentsReceived") == "function"
    page.evaluate("() => window.__off()")
    assert page.evaluate("() => typeof window.onNativeDocumentsReceived") == "undefined"
    assert page.evaluate("() => window.__share([{ name: 'Later.pdf' }])") == "queued"

    res = page.evaluate("() => window.native.consumeReceivedDocuments()")
    assert [d["name"] for d in res["documents"]] == ["Later.pdf"]
    assert page.evaluate("() => window.native.consumeReceivedDocuments()") == {
        "ok": True,
        "documents": [],
    }


def test_receive_documents_in_old_apps_and_the_browser(page: Page) -> None:
    open_page(page, "/?oldApp")
    res = page.evaluate(
        """async () => {
          const off = window.native.onDocumentsReceived(() => {})
          const consumed = await window.native.consumeReceivedDocuments()
          off()
          return consumed
        }"""
    )
    assert res == {"ok": False, "error": "unavailable"}
    assert [m for m in _log(page) if m["action"] == "consumeReceivedDocuments"] == []
    open_page(page, "/?browser")
    assert page.evaluate("() => window.native.consumeReceivedDocuments()") == {
        "ok": False,
        "error": "unavailable",
    }


# --- previewFile ------------------------------------------------------------------


def test_preview_file_downloads_from_the_own_origin_and_shows_it(page: Page) -> None:
    open_page(page)
    res = page.evaluate(
        "() => window.native.previewFile({ url: '/files/offer.pdf', filename: 'Offer 4711.pdf' })"
    )

    assert res == {"ok": True}
    origin = page.evaluate("() => location.origin")
    assert _log(page) == [
        {"action": "previewFile", "url": f"{origin}/files/offer.pdf", "filename": "Offer 4711.pdf"}
    ]
    [shown] = page.evaluate("() => window.__docs.previews")
    assert (shown["filename"], shown["size"]) == ("Offer 4711.pdf", len(b"%PDF-1.4 e2e"))


def test_preview_file_reports_the_http_status(page: Page) -> None:
    open_page(page)
    res = page.evaluate("() => window.native.previewFile({ url: '/files/missing.pdf' })")
    assert res == {"ok": False, "error": "failed", "status": 404}
    assert page.evaluate("() => window.__docs.previews") == []


def test_preview_file_refuses_another_origin_before_asking_the_app(page: Page) -> None:
    open_page(page)
    res = page.evaluate(
        "() => window.native.previewFile({ url: 'https://other.example.com/a.pdf' })"
    )
    assert res["error"] == "invalid"
    assert _log(page) == []
    # The app would refuse it as well.
    raw = page.evaluate(
        "() => window.native.call('previewFile', { url: 'https://other.example.com/a.pdf' })"
    )
    assert raw["error"] == "invalid"


def test_preview_file_in_the_browser_opens_a_tab(page: Page) -> None:
    open_page(page, "/?browser")
    with page.expect_popup() as popup:
        res = page.evaluate("() => window.native.previewFile({ url: '/files/offer.txt' })")
    assert res == {"ok": True}
    popup.value.wait_for_load_state()
    assert popup.value.url.endswith("/files/offer.txt")
    assert _log(page) == []


def test_preview_file_in_an_old_app_is_unavailable(page: Page) -> None:
    open_page(page, "/?oldApp")
    assert page.evaluate("() => window.native.previewFile({ url: '/files/offer.pdf' })") == {
        "ok": False,
        "error": "unavailable",
    }
    assert _log(page) == []


# --- the fixtures against the package and the app ---------------------------------


def _cases() -> list[tuple[str, str, str, dict]]:
    """(file, action, function, case) for every `options` case of the fixtures."""
    cases = []
    for file, action, function in (
        ("scan-result.json", "scanDocument", "scanDocument"),
        ("pick-files.json", "pickFiles", "pickFiles"),
        ("dictate.json", "dictate", "dictate"),
        ("preview-file.json", "previewFile", "previewFile"),
        ("access-token-resource.json", "getAccessToken", "getAccessToken"),
    ):
        options = _fixture(file)["options"]
        for kind in ("valid", "invalid"):
            for case in options.get(kind, []):
                cases.append((file, action, function, {**case, "kind": kind}))
    return cases


def _expand(value: Any, origin: str, key: str = "") -> Any:
    if isinstance(value, str):
        if value.startswith("@") and value[1:].isdigit():
            n = int(value[1:])
            return ["a"] * n if key == "contextualStrings" else "x" * n
        return value.replace("{origin}", origin)
    if isinstance(value, list):
        return [_expand(v, origin) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v, origin, k) for k, v in value.items()}
    return value


@pytest.mark.parametrize(
    ("file", "action", "function", "case"),
    _cases(),
    ids=lambda v: v["name"] if isinstance(v, dict) else str(v),
)
def test_option_fixtures_run_through_the_package_and_the_app(
    page: Page, file: str, action: str, function: str, case: dict
) -> None:
    open_page(page)
    origin = page.evaluate("() => location.origin")
    value = _expand(case["value"], origin)

    if case["kind"] == "valid":
        sent = _expand(case.get("sent", case["value"]), origin)
        page.evaluate(f"(options) => window.native.{function}(options)", value)
        assert _log(page) == [{**sent, "action": action}]
        return

    # Invalid: the package answers `invalid` and does not ask the app ...
    res = page.evaluate(f"(options) => window.native.{function}(options)", value)
    assert res["error"] == case["error"] == "invalid"
    assert _log(page) == []
    # ... and the app (played by the Python harness) refuses the same payload.
    raw = page.evaluate(f"(options) => window.native.call('{action}', options)", value)
    assert raw["error"] == "invalid"
