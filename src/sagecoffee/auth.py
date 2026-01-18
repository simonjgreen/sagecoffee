"""Authentication module for Breville/Sage OAuth (Auth0)."""

import base64
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from sagecoffee.models import TokenSet


def _utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(UTC)


# Auth0 endpoints
OAUTH_TOKEN_URL = "https://my.breville.com/oauth/token"

# Default OAuth parameters
DEFAULT_CLIENT_ID = "gSo1NuhsGPs5J2e5zyw0oGaSqdqsq2vc"
DEFAULT_REALM = "Salesforce"
DEFAULT_SCOPE = "openid profile email offline_access"
DEFAULT_AUDIENCE = "https://iden-prod.us.auth0.com/userinfo"


def decode_jwt_without_verify(token: str) -> dict[str, Any]:
    """
    Decode a JWT token without verification.

    Only use this for reading claims like 'exp' and 'sub'.
    This does NOT verify the signature.

    Args:
        token: The JWT token string

    Returns:
        The decoded payload as a dictionary

    Raises:
        ValueError: If the token is malformed
    """
    try:
        # JWT format: header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT format: expected 3 parts")

        # Decode the payload (second part)
        payload_b64 = parts[1]

        # Add padding if necessary (JWT uses base64url without padding)
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding

        # Decode base64url (replace - with + and _ with /)
        payload_b64 = payload_b64.replace("-", "+").replace("_", "/")
        payload_json = base64.b64decode(payload_b64)

        return json.loads(payload_json)
    except Exception as e:
        raise ValueError(f"Failed to decode JWT: {e}") from e


def get_token_expiry(token: str) -> datetime | None:
    """
    Get the expiry time from a JWT token.

    Args:
        token: The JWT token string

    Returns:
        The expiry datetime (timezone-aware UTC), or None if not available
    """
    try:
        payload = decode_jwt_without_verify(token)
        exp = payload.get("exp")
        if exp:
            return datetime.fromtimestamp(exp, tz=UTC)
    except Exception:
        pass
    return None


class AuthClient:
    """Client for Breville Auth0 authentication."""

    def __init__(
        self,
        client_id: str,
        http_client: httpx.AsyncClient | None = None,
    ):
        """
        Initialize the auth client.

        Args:
            client_id: The Auth0 client ID
            http_client: Optional httpx client to use (for testing)
        """
        self.client_id = client_id
        self._http_client = http_client
        self._owns_client = http_client is None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient()
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client if we own it."""
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def password_realm_login(
        self,
        username: str,
        password: str,
        realm: str = DEFAULT_REALM,
        scope: str = DEFAULT_SCOPE,
        audience: str = DEFAULT_AUDIENCE,
    ) -> TokenSet:
        """
        Authenticate using password realm grant.

        This is used for initial bootstrap only. After obtaining tokens,
        use refresh_token for subsequent authentication.

        Args:
            username: User's email address
            password: User's password
            realm: Auth0 realm (default: Salesforce)
            scope: OAuth scopes to request
            audience: OAuth audience

        Returns:
            TokenSet with access_token, id_token, and refresh_token

        Raises:
            httpx.HTTPStatusError: If authentication fails
        """
        client = await self._get_client()

        payload = {
            "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
            "realm": realm,
            "scope": scope,
            "audience": audience,
            "client_id": self.client_id,
            "username": username,
            "password": password,
        }

        response = await client.post(
            OAUTH_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()

        data = response.json()
        return TokenSet(
            access_token=data.get("access_token"),
            id_token=data.get("id_token"),
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in", 86400),
            token_type=data.get("token_type", "Bearer"),
            scope=data.get("scope"),
            obtained_at=_utcnow(),
        )

    async def refresh(
        self,
        refresh_token: str,
        scope: str = "openid profile email",
    ) -> TokenSet:
        """
        Refresh tokens using a refresh token.

        Args:
            refresh_token: The refresh token from a previous auth
            scope: OAuth scopes to request (include openid to get id_token)

        Returns:
            TokenSet with fresh tokens

        Raises:
            httpx.HTTPStatusError: If refresh fails
        """
        client = await self._get_client()

        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
            "scope": scope,
        }

        response = await client.post(
            OAUTH_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()

        data = response.json()
        return TokenSet(
            access_token=data.get("access_token"),
            id_token=data.get("id_token"),
            refresh_token=data.get("refresh_token", refresh_token),  # May not be rotated
            expires_in=data.get("expires_in", 86400),
            token_type=data.get("token_type", "Bearer"),
            scope=data.get("scope"),
            obtained_at=_utcnow(),
        )

    async def ensure_fresh(
        self,
        tokens: TokenSet,
        skew_seconds: int = 60,
    ) -> TokenSet:
        """
        Ensure tokens are fresh, refreshing if necessary.

        Args:
            tokens: Current token set
            skew_seconds: Refresh this many seconds before expiry

        Returns:
            Fresh TokenSet (may be the same object if not expired)

        Raises:
            ValueError: If no refresh token is available
            httpx.HTTPStatusError: If refresh fails
        """
        if not tokens.is_expired(skew_seconds):
            return tokens

        if not tokens.refresh_token:
            raise ValueError("Cannot refresh: no refresh_token available")

        return await self.refresh(tokens.refresh_token)


class SyncAuthClient:
    """Synchronous wrapper for AuthClient."""

    def __init__(self, client_id: str):
        """Initialize the sync auth client."""
        self.client_id = client_id

    def password_realm_login(
        self,
        username: str,
        password: str,
        realm: str = DEFAULT_REALM,
        scope: str = DEFAULT_SCOPE,
        audience: str = DEFAULT_AUDIENCE,
    ) -> TokenSet:
        """Authenticate using password realm grant (sync version)."""
        payload = {
            "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
            "realm": realm,
            "scope": scope,
            "audience": audience,
            "client_id": self.client_id,
            "username": username,
            "password": password,
        }

        with httpx.Client() as client:
            response = client.post(
                OAUTH_TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()

            data = response.json()
            return TokenSet(
                access_token=data.get("access_token"),
                id_token=data.get("id_token"),
                refresh_token=data.get("refresh_token"),
                expires_in=data.get("expires_in", 86400),
                token_type=data.get("token_type", "Bearer"),
                scope=data.get("scope"),
                obtained_at=_utcnow(),
            )

    def refresh(
        self,
        refresh_token: str,
        scope: str = "openid profile email",
    ) -> TokenSet:
        """Refresh tokens using a refresh token (sync version)."""
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
            "scope": scope,
        }

        with httpx.Client() as client:
            response = client.post(
                OAUTH_TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()

            data = response.json()
            return TokenSet(
                access_token=data.get("access_token"),
                id_token=data.get("id_token"),
                refresh_token=data.get("refresh_token", refresh_token),
                expires_in=data.get("expires_in", 86400),
                token_type=data.get("token_type", "Bearer"),
                scope=data.get("scope"),
                obtained_at=_utcnow(),
            )

    def ensure_fresh(
        self,
        tokens: TokenSet,
        skew_seconds: int = 60,
    ) -> TokenSet:
        """Ensure tokens are fresh, refreshing if necessary (sync version)."""
        if not tokens.is_expired(skew_seconds):
            return tokens

        if not tokens.refresh_token:
            raise ValueError("Cannot refresh: no refresh_token available")

        return self.refresh(tokens.refresh_token)
