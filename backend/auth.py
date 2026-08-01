"""Clerk JWT verification.

Every authenticated request from the frontend carries a Clerk session token
in the Authorization header. We verify it against Clerk's public JWKS and
extract the user ID (`sub` claim).
"""
import time
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient

from src.config import CLERK_ISSUER, CLERK_JWKS_URL

# Cache the JWKS client across requests (rotates keys internally).
_jwks_client: PyJWKClient | None = None
_jwks_last_error: str | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client, _jwks_last_error
    if not CLERK_JWKS_URL:
        raise HTTPException(
            status_code=500,
            detail="Clerk not configured. Set CLERK_PUBLISHABLE_KEY.",
        )
    if _jwks_client is None:
        _jwks_client = PyJWKClient(CLERK_JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwks_client


def verify_clerk_token(token: str) -> dict:
    """Verify a Clerk session token and return its claims."""
    try:
        jwks = _get_jwks_client()
        signing_key = jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=CLERK_ISSUER,
            options={
                # Clerk session tokens don't include `aud` by default; skip it.
                "verify_aud": False,
            },
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid session token: {e}")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Auth service unreachable: {e}")

    # Clerk-specific: check `nbf` and expiration manually if needed
    now = int(time.time())
    if claims.get("exp") and claims["exp"] < now:
        raise HTTPException(status_code=401, detail="Session token expired")

    return claims


def current_user_id(authorization: str | None = Header(None)) -> str:
    """FastAPI dependency: returns the Clerk user_id (`sub`) for the caller.
    Raises 401 if missing or invalid."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    token = authorization[len("Bearer "):].strip()
    claims = verify_clerk_token(token)
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing `sub` claim")
    return user_id
