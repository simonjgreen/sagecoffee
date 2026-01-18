"""Tests for the auth module."""

from datetime import UTC, datetime, timedelta

import pytest

from sagecoffee.auth import decode_jwt_without_verify, get_token_expiry
from sagecoffee.models import TokenSet


class TestDecodeJwt:
    """Tests for JWT decoding."""

    def test_decode_valid_jwt(self, sample_jwt: str) -> None:
        """Test decoding a valid JWT."""
        payload = decode_jwt_without_verify(sample_jwt)

        assert payload["sub"] == "auth0|0058b00000FK4DTAA1"
        assert payload["exp"] == 9999999999
        assert payload["iat"] == 1600000000

    def test_decode_invalid_jwt_format(self) -> None:
        """Test that invalid JWT format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid JWT format"):
            decode_jwt_without_verify("not.a.valid.jwt.token")

    def test_decode_invalid_jwt_single_part(self) -> None:
        """Test that single-part string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid JWT format"):
            decode_jwt_without_verify("notajwt")

    def test_decode_jwt_with_padding(self) -> None:
        """Test JWT decoding handles base64 padding correctly."""
        # This JWT has a payload that needs padding
        payload = decode_jwt_without_verify("eyJhbGciOiJIUzI1NiJ9.eyJhIjoiYiJ9.sig")
        assert payload["a"] == "b"


class TestGetTokenExpiry:
    """Tests for token expiry extraction."""

    def test_get_expiry_from_valid_jwt(self, sample_jwt: str) -> None:
        """Test getting expiry from a valid JWT."""
        expiry = get_token_expiry(sample_jwt)

        assert expiry is not None
        assert expiry == datetime.fromtimestamp(9999999999, tz=UTC)

    def test_get_expiry_from_invalid_jwt(self) -> None:
        """Test that invalid JWT returns None."""
        expiry = get_token_expiry("invalid")
        assert expiry is None


class TestTokenSet:
    """Tests for TokenSet model."""

    def test_is_expired_with_valid_token(self, sample_jwt: str) -> None:
        """Test is_expired returns False for valid token."""
        tokens = TokenSet(id_token=sample_jwt)
        assert not tokens.is_expired()

    def test_is_expired_with_expired_token(self, expired_jwt: str) -> None:
        """Test is_expired returns True for expired token."""
        tokens = TokenSet(id_token=expired_jwt)
        assert tokens.is_expired()

    def test_is_expired_with_no_token(self) -> None:
        """Test is_expired returns True when no token."""
        tokens = TokenSet()
        assert tokens.is_expired()

    def test_is_expired_with_skew(self, sample_jwt: str) -> None:
        """Test is_expired respects skew_seconds."""
        tokens = TokenSet(id_token=sample_jwt)
        # Even with huge skew, this far-future token shouldn't be expired
        assert not tokens.is_expired(skew_seconds=86400 * 365)

    def test_is_expired_fallback_to_obtained_at(self) -> None:
        """Test is_expired falls back to obtained_at + expires_in."""
        # Token without exp claim would fall back
        tokens = TokenSet(
            access_token="not_a_jwt",
            expires_in=3600,
            obtained_at=datetime.now(UTC) - timedelta(hours=2),
        )
        assert tokens.is_expired()

    def test_auth0_sub(self, sample_jwt: str) -> None:
        """Test extracting auth0 sub from id_token."""
        tokens = TokenSet(id_token=sample_jwt)
        assert tokens.auth0_sub() == "auth0|0058b00000FK4DTAA1"

    def test_auth0_sub_no_token(self) -> None:
        """Test auth0_sub returns None when no id_token."""
        tokens = TokenSet()
        assert tokens.auth0_sub() is None


class TestUrlEncoding:
    """Tests for URL encoding of auth0 subject."""

    def test_auth0_sub_encoding(self) -> None:
        """Test that auth0|... is URL encoded correctly."""
        from urllib.parse import quote

        sub = "auth0|0058b00000FK4DTAA1"
        encoded = quote(sub, safe="")

        assert encoded == "auth0%7C0058b00000FK4DTAA1"
        assert "|" not in encoded
