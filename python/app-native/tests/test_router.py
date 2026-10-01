from __future__ import annotations

import httpx
import pytest
from bmsdna.app_native import (
    DeviceRegistration,
    LocationUpdate,
    WidgetRequestContext,
    create_ingest_router,
    insecure_no_auth,
)
from fastapi import FastAPI, HTTPException


@pytest.mark.asyncio
async def test_callbacks_receive_payloads_unmodified() -> None:
    received_devices: list[DeviceRegistration] = []
    received_locations: list[LocationUpdate] = []

    async def on_device(body: DeviceRegistration, context: WidgetRequestContext) -> None:
        received_devices.append(body)

    async def on_location(body: LocationUpdate, context: WidgetRequestContext) -> None:
        received_locations.append(body)

    app = FastAPI()
    app.include_router(
        create_ingest_router(
            on_device_registered=on_device,
            on_location_received=on_location,
            auth_dependency=insecure_no_auth,
        ),
        prefix="/api",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        device_response = await client.post(
            "/api/devices", json={"device_id": "abc", "push_token": "deadbeef"}
        )
        location_response = await client.post(
            "/api/locations", json={"device_id": "abc", "latitude": 47.0, "longitude": 8.0}
        )

    assert device_response.status_code == 200
    assert location_response.status_code == 200
    assert received_devices[0].device_id == "abc"
    assert received_devices[0].push_token == "deadbeef"
    assert "push_token" in received_devices[0].model_fields_set
    assert "user_email" not in received_devices[0].model_fields_set
    assert received_locations[0].latitude == 47.0


@pytest.mark.asyncio
async def test_auth_dependency_is_enforced() -> None:
    async def on_device(body: DeviceRegistration, context: WidgetRequestContext) -> None:
        pass

    async def on_location(body: LocationUpdate, context: WidgetRequestContext) -> None:
        pass

    async def deny() -> None:
        raise HTTPException(status_code=401, detail="nope")

    app = FastAPI()
    app.include_router(
        create_ingest_router(
            on_device_registered=on_device,
            on_location_received=on_location,
            auth_dependency=deny,
        ),
        prefix="/api",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/devices", json={"device_id": "abc"})

    assert response.status_code == 401


def test_auth_dependency_is_required() -> None:
    async def noop(body: object, context: WidgetRequestContext) -> None:
        return None

    with pytest.raises(TypeError, match="auth_dependency"):
        create_ingest_router(on_device_registered=noop, on_location_received=noop)  # ty: ignore[missing-argument]


@pytest.mark.asyncio
async def test_callbacks_get_the_authenticated_user() -> None:
    seen: list[tuple[object, str | None]] = []

    async def on_device(body: DeviceRegistration, context: WidgetRequestContext) -> None:
        seen.append((context.user, body.user_email))

    async def on_location(body: LocationUpdate, context: WidgetRequestContext) -> None:
        return None

    async def entra_like() -> dict[str, str]:
        return {"upn": "real.user@example.com"}

    app = FastAPI()
    app.include_router(
        create_ingest_router(
            on_device_registered=on_device,
            on_location_received=on_location,
            auth_dependency=entra_like,
        ),
        prefix="/api",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            "/api/devices", json={"device_id": "abc", "user_email": "victim@example.com"}
        )

    # The body claims another user, the callback can tell who really called.
    assert seen == [({"upn": "real.user@example.com"}, "victim@example.com")]


@pytest.mark.asyncio
@pytest.mark.parametrize(("latitude", "longitude"), [(91, 8), (-91, 8), (47, 181), (47, -181)])
async def test_location_out_of_range_is_rejected(latitude: float, longitude: float) -> None:
    async def on_device(body: DeviceRegistration, context: WidgetRequestContext) -> None:
        return None

    async def on_location(body: LocationUpdate, context: WidgetRequestContext) -> None:
        raise AssertionError("must not be called")

    app = FastAPI()
    app.include_router(
        create_ingest_router(
            on_device_registered=on_device,
            on_location_received=on_location,
            auth_dependency=insecure_no_auth,
        ),
        prefix="/api",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/locations",
            json={"device_id": "abc", "latitude": latitude, "longitude": longitude},
        )

    assert response.status_code == 422
