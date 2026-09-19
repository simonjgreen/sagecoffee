"""Tests for the logging module."""

from sagecoffee.logging import redact, redact_dict, redact_string


class TestRedact:
    """Tests for the redact function."""

    def test_redact_long_string(self) -> None:
        """Test redacting a long string."""
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature"
        result = redact(token)

        assert result.startswith("eyJhbGci")
        assert result.endswith("nature")
        assert "..." in result
        assert len(result) < len(token)

    def test_redact_short_string(self) -> None:
        """Test redacting a short string (should mask entirely)."""
        result = redact("short")
        assert result == "*****"

    def test_redact_empty_string(self) -> None:
        """Test redacting empty string."""
        result = redact("")
        assert result == ""

    def test_redact_custom_lengths(self) -> None:
        """Test redact with custom keep lengths."""
        token = "abcdefghijklmnopqrstuvwxyz"
        result = redact(token, keep_start=4, keep_end=4)

        assert result.startswith("abcd")
        assert result.endswith("wxyz")
        assert "..." in result


class TestRedactDict:
    """Tests for the redact_dict function."""

    def test_redact_sensitive_keys(self) -> None:
        """Test that sensitive keys are redacted."""
        data = {
            "access_token": "secret_token_value_12345678901234567890",
            "refresh_token": "another_secret_12345678901234567890",
            "password": "mypassword12345678901234567890",
            "username": "user@example.com",
        }

        result = redact_dict(data)

        assert "..." in result["access_token"]
        assert "..." in result["refresh_token"]
        assert "..." in result["password"]
        assert result["username"] == "user@example.com"  # Not sensitive

    def test_redact_nested_dict(self) -> None:
        """Test that nested dicts are redacted."""
        data = {
            "outer": {
                "id_token": "nested_token_12345678901234567890",
                "name": "test",
            }
        }

        result = redact_dict(data, deep=True)

        assert "..." in result["outer"]["id_token"]
        assert result["outer"]["name"] == "test"

    def test_redact_headers(self) -> None:
        """Test that header-style keys are redacted."""
        data = {
            "sf-id-token": "header_token_12345678901234567890",
            "Authorization": "Bearer secret12345678901234567890",
        }

        result = redact_dict(data)

        assert "..." in result["sf-id-token"]
        assert "..." in result["Authorization"]


class TestRedactString:
    """Tests for the redact_string function."""

    def test_redact_jwt_in_string(self) -> None:
        """Test redacting a JWT found in a string."""
        text = "Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = redact_string(text)

        assert "..." in result
        assert "eyJhbGci" in result  # Start is preserved

    def test_redact_multiple_tokens(self) -> None:
        """Test redacting multiple tokens in a string."""
        text = "access=abc123def456ghi789jkl012mno345 refresh=xyz987wvu654tsr321qpo098nml765"
        result = redact_string(text)

        # Both long tokens should be redacted
        assert result.count("...") == 2

    def test_no_redact_short_strings(self) -> None:
        """Test that short strings are not redacted."""
        text = "Hello world"
        result = redact_string(text)

        assert result == text


class TestRedactingFilter:
    """Tests for the RedactingFilter logging filter."""

    def _format_through_filter(self, msg: str, *args: object) -> str:
        import logging

        from sagecoffee.logging import RedactingFilter

        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=args,
            exc_info=None,
        )
        assert RedactingFilter().filter(record) is True
        return record.getMessage()

    def test_single_dict_argument_is_formatted_and_redacted(self) -> None:
        """A lone dict argument must be rendered, not iterated as keys."""
        secret = "abcdefghijklmnopqrstuvwxyz0123456789"
        message = self._format_through_filter(
            "Sending: %s", {"action": "addAppliance", "refresh_token": secret}
        )

        assert "addAppliance" in message
        assert secret not in message
        assert message != "Sending: ('action', 'refresh_token')"

    def test_tuple_arguments_are_still_redacted(self) -> None:
        """Existing tuple handling keeps working."""
        secret = "abcdefghijklmnopqrstuvwxyz0123456789"
        message = self._format_through_filter("a=%s b=%s", secret, 42)

        assert secret not in message
        assert message.endswith("b=42")
