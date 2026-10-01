from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Request

from .models import DeviceRegistration, LocationUpdate
from .widgets import WidgetRequestContext

DeviceCallback = Callable[[DeviceRegistration, WidgetRequestContext], Awaitable[None]]
LocationCallback = Callable[[LocationUpdate, WidgetRequestContext], Awaitable[None]]


def create_ingest_router(
    *,
    on_device_registered: DeviceCallback,
    on_location_received: LocationCallback,
    auth_dependency: Callable[..., Any],
) -> APIRouter:
    """Builds an APIRouter to mount in your own backend, e.g.:

        app.include_router(
            create_ingest_router(
                on_device_registered=my_store.save_device,
                on_location_received=my_store.save_location,
                auth_dependency=require_user,  # your own auth, see `auth.py`
            ),
            prefix="/api",
        )

    Stores nothing itself — every update lands unchanged in your own
    callback together with the request context (`context.user` is what your
    `auth_dependency` returned). What you do with it (store it in your DB,
    process it live, pass it on to another service, ...) is up to you.
    `auth_dependency` is required and mounted as a FastAPI dependency, see
    `auth.py`. `user_email` in the body is client input: take the identity
    from `context.user`.
    """
    router = APIRouter()

    @router.post("/devices")
    async def register_device(
        body: DeviceRegistration, request: Request, user: Any = Depends(auth_dependency)
    ) -> dict[str, bool]:
        await on_device_registered(
            body, WidgetRequestContext(device_id=body.device_id, user=user, request=request)
        )
        return {"ok": True}

    @router.post("/locations")
    async def receive_location(
        body: LocationUpdate, request: Request, user: Any = Depends(auth_dependency)
    ) -> dict[str, bool]:
        await on_location_received(
            body, WidgetRequestContext(device_id=body.device_id, user=user, request=request)
        )
        return {"ok": True}

    return router
