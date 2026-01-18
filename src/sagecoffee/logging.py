"""Logging utilities with secret redaction for Sage Coffee library."""

import logging
import re
from typing import Any

# Patterns that look like tokens/secrets
TOKEN_PATTERNS = [
    re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # JWT
    re.compile(r"[A-Za-z0-9_-]{20,}"),  # Generic long token
]

# Keys that should be redacted in dictionaries
SENSITIVE_KEYS = {
    "password",
    "access_token",
    "id_token",
    "refresh_token",
    "token",
    "secret",
    "credential",
    "sf-id-token",
    "authorization",
}


def redact(value: str, keep_start: int = 8, keep_end: int = 6) -> str:
    """
    Redact a sensitive value, keeping only the start and end.

    Args:
        value: The value to redact
        keep_start: Number of characters to keep at the start
        keep_end: Number of characters to keep at the end

    Returns:
        Redacted string like "eyJhbGci...abc123"
    """
    if not value:
        return value

    if len(value) <= keep_start + keep_end + 3:
        # Too short to meaningfully redact
        return "*" * len(value)

    return f"{value[:keep_start]}...{value[-keep_end:]}"


def redact_dict(data: dict[str, Any], deep: bool = True) -> dict[str, Any]:
    """
    Redact sensitive values in a dictionary.

    Args:
        data: Dictionary to redact
        deep: Whether to recursively redact nested dicts

    Returns:
        New dictionary with redacted values
    """
    result = {}
    for key, value in data.items():
        key_lower = key.lower().replace("_", "").replace("-", "")

        # Check if this key should be redacted
        is_sensitive = any(
            sensitive.replace("_", "").replace("-", "") in key_lower for sensitive in SENSITIVE_KEYS
        )

        if is_sensitive and isinstance(value, str):
            result[key] = redact(value)
        elif deep and isinstance(value, dict):
            result[key] = redact_dict(value, deep=True)
        elif deep and isinstance(value, list):
            result[key] = [
                redact_dict(item, deep=True) if isinstance(item, dict) else item for item in value
            ]
        else:
            result[key] = value

    return result


def redact_string(text: str) -> str:
    """
    Redact any tokens/secrets found in a string.

    Args:
        text: Text that may contain secrets

    Returns:
        Text with secrets redacted
    """
    result = text
    for pattern in TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group()
            if len(token) > 20:  # Only redact if it looks like a real token
                result = result.replace(token, redact(token))
    return result


class RedactingFormatter(logging.Formatter):
    """Logging formatter that redacts sensitive information."""

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with redaction."""
        # Format normally first
        message = super().format(record)
        # Then redact any secrets
        return redact_string(message)


class RedactingFilter(logging.Filter):
    """Logging filter that redacts sensitive information in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter and redact the log record."""
        if isinstance(record.msg, str):
            record.msg = redact_string(record.msg)

        if record.args:
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    new_args.append(redact_string(arg))
                elif isinstance(arg, dict):
                    new_args.append(redact_dict(arg))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)

        return True


def setup_logging(
    level: int = logging.INFO,
    debug_http: bool = False,
    debug_ws: bool = False,
) -> logging.Logger:
    """
    Set up logging for the Sage Coffee library.

    Args:
        level: Base logging level
        debug_http: Enable HTTP debug logging
        debug_ws: Enable WebSocket debug logging

    Returns:
        Configured logger
    """
    # Create logger
    logger = logging.getLogger("sagecoffee")
    logger.setLevel(level)

    # Remove existing handlers
    logger.handlers.clear()

    # Create console handler with redacting formatter
    handler = logging.StreamHandler()
    handler.setLevel(level)

    formatter = RedactingFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    handler.addFilter(RedactingFilter())

    logger.addHandler(handler)

    # Configure HTTP logging
    if debug_http:
        httpx_logger = logging.getLogger("httpx")
        httpx_logger.setLevel(logging.DEBUG)
        httpx_logger.addHandler(handler)

    # Configure WebSocket logging
    if debug_ws:
        ws_logger = logging.getLogger("websockets")
        ws_logger.setLevel(logging.DEBUG)
        ws_logger.addHandler(handler)

    return logger


def get_logger(name: str = "sagecoffee") -> logging.Logger:
    """
    Get a logger for the Sage Coffee library.

    Args:
        name: Logger name (will be prefixed with 'sagecoffee.')

    Returns:
        Logger instance
    """
    if not name.startswith("sagecoffee"):
        name = f"sagecoffee.{name}"
    return logging.getLogger(name)
