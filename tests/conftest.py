"""Pytest configuration and fixtures."""

import pytest

# Configure pytest-asyncio
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture
def sample_jwt() -> str:
    """A sample JWT token for testing (not a real token)."""
    # This is a properly formatted but fake JWT
    # Header: {"alg": "HS256", "typ": "JWT"}
    # Payload: {"sub": "auth0|0058b00000FK4DTAA1", "exp": 9999999999, "iat": 1600000000}
    return (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiJhdXRoMHwwMDU4YjAwMDAwRks0RFRBQTEiLCJleHAiOjk5OTk5OTk5OTksImlhdCI6MTYwMDAwMDAwMH0."
        "fake_signature_here"
    )


@pytest.fixture
def expired_jwt() -> str:
    """An expired JWT token for testing."""
    # Payload: {"sub": "auth0|test", "exp": 1600000000, "iat": 1599999000}
    return (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiJhdXRoMHx0ZXN0IiwiZXhwIjoxNjAwMDAwMDAwLCJpYXQiOjE1OTk5OTkwMDB9."
        "fake_signature"
    )


@pytest.fixture
def sample_state_report() -> dict:
    """A sample state report from WebSocket."""
    return {
        "serialNumber": "A1SKAESA251400639",
        "messageType": "stateReport",
        "version": 123,
        "data": {
            "reported": {
                "state": "ready",
                "boiler": [
                    {"cur_temp": 93.5, "temp_sp": 94.0},
                    {"cur_temp": 140.0, "temp_sp": 140.0},
                ],
                "grind.size_setting": 15,
                "cfg.default": {
                    "remote_wake_enable": True,
                    "timezone": "Europe/London",
                },
            },
            "desired": {
                "state": "ready",
            },
        },
    }


@pytest.fixture
def sample_appliances_response() -> dict:
    """A sample appliances list response."""
    return {
        "appliances": [
            {
                "model": "BES995",
                "serialNumber": "A1SKAESA251400639",
                "name": "Oracle Dual Boiler",
                "pairingType": "wifi",
            },
            {
                "model": "BES920",
                "serialNumber": "B2TEST123456789",
                "name": "Dual Boiler",
                "pairingType": "wifi",
            },
        ],
        "ownedModels": [],
    }


@pytest.fixture
def sample_token_response() -> dict:
    """A sample OAuth token response."""
    return {
        "access_token": "fake_access_token_" + "x" * 100,
        "id_token": (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiJhdXRoMHwwMDU4YjAwMDAwRks0RFRBQTEiLCJleHAiOjk5OTk5OTk5OTksImlhdCI6MTYwMDAwMDAwMH0."
            "fake_signature"
        ),
        "refresh_token": "fake_refresh_token_" + "y" * 100,
        "expires_in": 86400,
        "token_type": "Bearer",
        "scope": "openid profile email offline_access",
    }
