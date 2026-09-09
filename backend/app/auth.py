"""Verifies Supabase-issued access tokens and exposes the current user's id.

Supabase's newer projects sign session tokens with an asymmetric key
(ES256 or RS256) rather than the older shared-secret (HS256) scheme. We
verify signatures against Supabase's public JWKS endpoint instead of a
secret -- the private key never leaves Supabase, so a leaked backend
`.env` can't be used to forge tokens the way a leaked shared secret could.
`PyJWKClient` fetches and caches the public keys for us, matching each
token to the right key by its `kid` header.

Every protected route depends on `get_current_user_id`, which fails
closed (raises 401) on any missing, malformed, expired, or badly signed
token. We never trust an id the client merely claims -- only one
extracted from a signature we verified ourselves.
"""

import logging

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from app.config import get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=True)
_jwks_url = f"{get_settings().supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
# Supabase's gateway requires an apikey header on every /auth/v1/* route,
# including this one -- without it, the JWKS fetch itself gets rejected
# with a 401 before we ever get to verify anything.
_jwks_client = PyJWKClient(
    _jwks_url,
    cache_keys=True,
    headers={"apikey": get_settings().supabase_publishable_key},
)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """Verify the Supabase access token and return the authenticated user's id."""
    token = credentials.credentials

    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
        )
    except (jwt.PyJWTError, PyJWKClientError) as exc:
        # Logged (not exposed to the client) so we can see the *real* reason
        # a token was rejected -- expired, wrong audience, JWKS unreachable,
        # bad signature, etc. -- instead of guessing from a generic message.
        logger.warning("Token verification failed (jwks_url=%s): %r", _jwks_url, exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please sign in again.",
        ) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing a subject claim.",
        )
    return user_id
