import pytest
from aioapns import NotificationRequest
from aioapns.connection import JWTAuthorizationHeaderProvider
from bmsdna.app_native import apns
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


@pytest.fixture
def pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def test_load_key_multiline(monkeypatch: pytest.MonkeyPatch, pem: str) -> None:
    monkeypatch.setenv("APNS_KEY", pem)

    key = apns._load_key()

    assert key == pem.strip()
    # aioapns signs with the contents, a path would fail here.
    assert JWTAuthorizationHeaderProvider(key, "KEYID", "TEAMID").get_header().startswith("bearer ")


def test_load_key_with_escaped_newlines(monkeypatch: pytest.MonkeyPatch, pem: str) -> None:
    monkeypatch.setenv("APNS_KEY", pem.strip().replace("\n", "\\n"))

    assert apns._load_key() == pem.strip()


def test_load_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APNS_KEY", raising=False)

    with pytest.raises(RuntimeError, match="APNS_KEY is missing"):
        apns._load_key()


def test_load_key_rejects_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APNS_KEY", "./keys/AuthKey.p8")

    with pytest.raises(RuntimeError, match="not PEM text"):
        apns._load_key()


# --- Runtime credentials ---------------------------------------------------


class _FakeResponse:
    is_successful = True
    description = None


class _FakeClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.requests: list[NotificationRequest] = []

    async def send_notification(self, request: NotificationRequest) -> _FakeResponse:
        self.requests.append(request)
        return _FakeResponse()


@pytest.fixture
def fake_clients(monkeypatch: pytest.MonkeyPatch) -> list[_FakeClient]:
    created: list[_FakeClient] = []

    def factory(**kwargs: object) -> _FakeClient:
        client = _FakeClient(**kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(apns, "APNs", factory)
    monkeypatch.setattr(apns, "_clients", {})
    monkeypatch.setattr(apns, "_config_provider", None)
    for name in ("APNS_KEY", "APNS_KEY_ID", "APNS_TEAM_ID", "APNS_BUNDLE_ID", "APNS_USE_SANDBOX"):
        monkeypatch.delenv(name, raising=False)
    return created


def _config(
    pem: str,
    *,
    key_id: str = "KEYID",
    bundle_id: str = "ch.example.app",
    use_sandbox: bool = True,
) -> apns.ApnsConfig:
    return apns.ApnsConfig(
        key=pem, key_id=key_id, team_id="TEAMID", bundle_id=bundle_id, use_sandbox=use_sandbox
    )


async def test_explicit_config(fake_clients: list[_FakeClient], pem: str) -> None:
    sent, detail = await apns.send_push(
        device_token="tok", title="t", body="b", config=_config(pem, use_sandbox=False)
    )

    assert (sent, detail) == (True, None)
    (client,) = fake_clients
    assert client.kwargs["key_id"] == "KEYID"
    assert client.kwargs["topic"] == "ch.example.app"
    assert client.kwargs["use_sandbox"] is False
    assert len(client.requests) == 1


async def test_config_accepts_escaped_newlines(fake_clients: list[_FakeClient], pem: str) -> None:
    config = _config(pem.strip().replace("\n", "\n"))

    assert config.key == pem.strip()


async def test_provider_is_called_before_every_send(
    fake_clients: list[_FakeClient], pem: str
) -> None:
    calls = 0

    async def provider() -> apns.ApnsConfig:
        nonlocal calls
        calls += 1
        return _config(pem)

    apns.set_apns_config_provider(provider)
    await apns.send_silent_push(device_token="tok")
    await apns.send_silent_push(device_token="tok")

    assert calls == 2
    assert len(fake_clients) == 1  # same credentials, one client


async def test_explicit_config_beats_provider(fake_clients: list[_FakeClient], pem: str) -> None:
    async def provider() -> apns.ApnsConfig:
        raise AssertionError("provider must not be called")

    apns.set_apns_config_provider(provider)
    await apns.send_approvals_update(device_token="tok", webapp_id="w", config=_config(pem))

    assert len(fake_clients) == 1


async def test_provider_beats_environment_and_can_be_removed(
    fake_clients: list[_FakeClient], pem: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APNS_KEY", pem)
    monkeypatch.setenv("APNS_KEY_ID", "ENVKEY")
    monkeypatch.setenv("APNS_TEAM_ID", "TEAMID")
    monkeypatch.setenv("APNS_BUNDLE_ID", "ch.example.env")

    async def provider() -> apns.ApnsConfig:
        return _config(pem, key_id="PROVKEY")

    apns.set_apns_config_provider(provider)
    await apns.send_silent_push(device_token="tok")
    apns.set_apns_config_provider(None)
    await apns.send_silent_push(device_token="tok")

    assert [c.kwargs["key_id"] for c in fake_clients] == ["PROVKEY", "ENVKEY"]


async def test_environment_fallback(
    fake_clients: list[_FakeClient], pem: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APNS_KEY", pem)
    monkeypatch.setenv("APNS_KEY_ID", "ENVKEY")
    monkeypatch.setenv("APNS_TEAM_ID", "TEAMID")
    monkeypatch.setenv("APNS_BUNDLE_ID", "ch.example.env")

    await apns.send_push(device_token="tok", title="t", body="b")

    (client,) = fake_clients
    assert client.kwargs["topic"] == "ch.example.env"
    assert client.kwargs["use_sandbox"] is True


async def test_missing_configuration_raises(fake_clients: list[_FakeClient]) -> None:
    with pytest.raises(RuntimeError, match="not configured"):
        await apns.send_push(device_token="tok", title="t", body="b")


async def test_changed_key_builds_new_client_and_drops_old(
    fake_clients: list[_FakeClient], pem: str
) -> None:
    other_pem = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )

    await apns.send_silent_push(device_token="tok", config=_config(pem))
    await apns.send_silent_push(device_token="tok", config=_config(pem))
    assert len(fake_clients) == 1

    await apns.send_silent_push(device_token="tok", config=_config(other_pem))

    assert len(fake_clients) == 2
    assert fake_clients[1].kwargs["key"] == other_pem.strip()
    assert len(apns._clients) == 1
    assert all(pem.strip() not in str(k) for k in apns._clients)


def test_live_activity_topic_from_config(pem: str) -> None:
    config = _config(pem, bundle_id="ch.example.other")

    assert apns.live_activity_topic(config) == "ch.example.other.push-type.liveactivity"


async def test_live_activity_uses_config_topic(fake_clients: list[_FakeClient], pem: str) -> None:
    from bmsdna.app_native import LiveActivityState, send_live_activity_update

    await send_live_activity_update(
        push_token="tok",
        state=LiveActivityState(title="x", status="y", progress=0.5),
        config=_config(pem, bundle_id="ch.example.la"),
    )

    (client,) = fake_clients
    (request,) = client.requests
    assert request.apns_topic == "ch.example.la.push-type.liveactivity"


def test_config_repr_hides_key(pem: str) -> None:
    config = _config(pem)

    assert pem.strip() not in repr(config)
    assert "BEGIN PRIVATE KEY" not in repr(config)
    assert "BEGIN PRIVATE KEY" not in str(config)


async def test_no_key_in_logs(
    fake_clients: list[_FakeClient], pem: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("DEBUG"):
        await apns.send_push(device_token="tok", title="t", body="b", config=_config(pem))

    assert "BEGIN PRIVATE KEY" not in caplog.text


def test_config_rejects_non_pem() -> None:
    with pytest.raises(RuntimeError, match="not PEM text"):
        apns.ApnsConfig(key="./AuthKey.p8", key_id="K", team_id="T", bundle_id="b")
