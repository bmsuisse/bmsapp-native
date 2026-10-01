import pytest
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
