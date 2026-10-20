import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app import auth
from app.config import get_settings

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeJwks:
    def get_signing_key_from_jwt(self, token):
        return KEY.public_key()


@pytest.fixture(autouse=True)
def fake_jwks(monkeypatch):
    monkeypatch.setattr(auth, "_jwks_client", lambda: _FakeJwks())


def _token(**overrides):
    settings = get_settings()
    claims = {
        "sub": "user-1",
        "iss": settings.cognito_issuer,
        "client_id": settings.cognito_client_id,
        "token_use": "access",
        "exp": int(time.time()) + 300,
    } | overrides
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=jwt.encode(claims, KEY, algorithm="RS256"))


def test_valid_access_token():
    assert auth.get_current_user(_token()).owner_id == "user-1"


@pytest.mark.parametrize(
    "overrides",
    [{"token_use": "id"}, {"client_id": "other"}, {"iss": "http://evil"}, {"exp": int(time.time()) - 60}],
)
def test_rejected_tokens(overrides):
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(_token(**overrides))
    assert exc.value.status_code == 401 and exc.value.detail == "Not authenticated"


def test_missing_header():
    with pytest.raises(HTTPException):
        auth.get_current_user(None)
