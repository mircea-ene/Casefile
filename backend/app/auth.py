from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    sub: str

    @property
    def owner_id(self) -> str:
        # Single place to switch data scoping to a tenant id derived from the token.
        return self.sub


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    # Caches keys and refetches the JWKS when it sees an unknown `kid`.
    return jwt.PyJWKClient(get_settings().cognito_jwks_url, cache_keys=True)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    settings = get_settings()
    try:
        key = _jwks_client().get_signing_key_from_jwt(credentials.credentials)
        claims = jwt.decode(
            credentials.credentials,
            key,
            algorithms=["RS256"],
            issuer=settings.cognito_issuer,
            options={"verify_aud": False, "require": ["exp", "iss", "sub"]},
            leeway=30,
        )
    except jwt.PyJWTError:
        raise _unauthorized()

    if claims.get("token_use") != "access" or claims.get("client_id") != settings.cognito_client_id:
        raise _unauthorized()

    return CurrentUser(sub=claims["sub"])
