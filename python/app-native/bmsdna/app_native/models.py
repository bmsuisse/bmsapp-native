from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DeviceRegistration(BaseModel):
    """Payload of POST <prefix>/devices.

    Only `device_id` is required. `push_token` and `user_email` can arrive
    independently of each other — push registration often happens before
    login, and conversely the logged-in user can change without the push
    token changing. `user_email` is reported by the client and unverified:
    take the identity from the `context.user` of your `auth_dependency`.
    `model_fields_set` (a standard attribute of every
    Pydantic model) tells your callback which fields were actually sent in
    this particular call — if a field is missing, an existing value should
    usually be left untouched; if it is explicitly `null`, that is a
    deliberate deletion (e.g. `user_email: null` on logout).
    """

    device_id: str
    push_token: str | None = None
    platform: Literal["ios"] | None = None
    user_email: str | None = None


class LocationUpdate(BaseModel):
    """Payload of POST <prefix>/locations — a single location update,
    already throttled on the client side (minimum time/distance between two
    updates)."""

    device_id: str
    user_email: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = None
    recorded_at: datetime | None = None
