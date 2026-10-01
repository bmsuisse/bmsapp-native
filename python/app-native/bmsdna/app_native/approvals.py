"""Approvals inbox: pending approvals of all web apps in one place.

Each web app delivers the approvals currently waiting for the logged-in user
(vacation requests, expenses, orders, ...). The app collects them at the top
of the home dashboard ("Waiting for you") and in a separate list, where the
user approves or rejects by swiping or tapping, without opening the web
app. Content and logic live entirely in your backend:

1. **Feed** (`GET <prefix>/approvals`): The app fetches it itself, on
   launch, when returning to the foreground and via pull-to-refresh.
2. **Decision** (`POST <prefix>/approval-decisions`): Approve or reject,
   optionally with a comment. Your response can update the list right
   away.
3. **Push** (`send_approvals_update`): A silent push makes the app reload
   the feed immediately, e.g. when a new request comes in.

Both are mounted by `create_approvals_router()`. In the app, the web app
needs the `.approvals` capability for this.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .widgets import WidgetRequestContext, _CamelModel

#: Whether a comment is requested when approving or rejecting.
CommentRequirement = Literal["none", "optional", "required"]


class ApprovalDetail(_CamelModel):
    """A row in the detail view, e.g. `Period: November 3–7`."""

    label: str
    value: str


class Approval(_CamelModel):
    """A pending approval for the requesting user."""

    #: Stable across fetches, comes back as `approval_id` with the
    #: decision.
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    #: Second line in the list, e.g. "Anna Muster · November 3–7".
    subtitle: str | None = None
    #: Type of approval, small above the title, e.g. "Vacation", "Expenses".
    category: str | None = None
    #: Highlighted value on the right, e.g. "CHF 1'240" or "5 days".
    amount: str | None = None
    #: Who submitted the request.
    requester: str | None = None
    created_at: datetime | None = None
    #: Deadline. The app shows it and marks overdue approvals.
    due_at: datetime | None = None
    #: Highlight in red and sort to the top of the list.
    urgent: bool | None = None
    #: SF Symbol, defaults to the web app's icon.
    icon: str | None = None
    #: Further information in the detail view (at most 12 are shown).
    details: list[ApprovalDetail] | None = None
    #: Path in your web app for "Open details in the app".
    path: str | None = None
    #: Button labels, default "Approve" or "Reject".
    approve_label: str | None = None
    reject_label: str | None = None
    #: Ask for a comment. Default: never when approving, optional when
    #: rejecting.
    approve_comment: CommentRequirement | None = None
    reject_comment: CommentRequirement | None = None
    #: Approve only after Face ID/Touch ID. This is only a UX confirmation
    #: on the device, not proof that can be verified on the server.
    biometric: bool | None = None


class ApprovalFeed(_CamelModel):
    """Response to `GET <prefix>/approvals`."""

    approvals: list[Approval] = Field(default_factory=list)


class ApprovalDecisionReceived(BaseModel):
    """Payload of `POST <prefix>/approval-decisions`."""

    device_id: str
    approval_id: str
    decision: Literal["approve", "reject"]
    #: The user's comment, if requested and filled in.
    comment: str | None = None
    #: Email the app reports for the signed-in user, if the web app has
    #: `.identity`. Unverified client input: use `context.user` from your
    #: `auth_dependency` for identity and permissions.
    user_email: str | None = None


class ApprovalDecisionResult(_CamelModel):
    """Response to a decision. All fields are optional."""

    #: `False` reports a refusal (e.g. "Already handled by someone
    #: else"). The approval then stays in the list.
    ok: bool = True
    #: Short banner in the app. Without `message` the app shows
    #: "Approved" or "Rejected".
    message: str | None = None
    style: Literal["info", "success", "warning", "error"] | None = None
    #: Replaces ALL pending approvals of your web app on the device. Without
    #: `approvals` the app only removes the one just decided.
    approvals: list[Approval] | None = None


ApprovalProvider = Callable[[WidgetRequestContext], Awaitable[Sequence[Approval]]]
ApprovalDecisionCallback = Callable[
    [ApprovalDecisionReceived, WidgetRequestContext],
    Awaitable[ApprovalDecisionResult | None],
]


def create_approvals_router(
    *,
    get_approvals: ApprovalProvider,
    on_decision: ApprovalDecisionCallback,
    auth_dependency: Callable[..., Any],
) -> APIRouter:
    """Builds an APIRouter for `GET <prefix>/approvals` and
    `POST <prefix>/approval-decisions`.

    `get_approvals` returns what is currently waiting for the user. The app
    replaces all approvals of your web app with it, so one that is no longer
    returned disappears. `on_decision` carries out approve/reject. Return
    `None` for a plain "ok", or an `ApprovalDecisionResult`.

    `auth_dependency` authenticates the calls (see `auth.py`); its result is
    available in `context.user`. In `on_decision`, always check
    yourself whether this user may decide the approval: `approval_id`
    comes from the device.
    """
    router = APIRouter()
    auth = auth_dependency

    @router.get(
        "/approvals",
        response_model=ApprovalFeed,
        response_model_by_alias=True,
        response_model_exclude_none=True,
    )
    async def get_feed(
        request: Request, device_id: str | None = None, user: Any = Depends(auth)
    ) -> ApprovalFeed:
        approvals = await get_approvals(
            WidgetRequestContext(device_id=device_id, user=user, request=request)
        )
        return ApprovalFeed(approvals=list(approvals))

    @router.post(
        "/approval-decisions",
        response_model=ApprovalDecisionResult,
        response_model_by_alias=True,
        response_model_exclude_none=True,
    )
    async def receive_decision(
        body: ApprovalDecisionReceived, request: Request, user: Any = Depends(auth)
    ) -> ApprovalDecisionResult:
        result = await on_decision(
            body,
            WidgetRequestContext(device_id=body.device_id, user=user, request=request),
        )
        return result or ApprovalDecisionResult()

    return router
