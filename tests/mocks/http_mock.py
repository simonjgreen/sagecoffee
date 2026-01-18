"""Mock HTTP transport for testing."""

from collections.abc import Callable
from typing import Any

import httpx


class MockTransport(httpx.MockTransport):
    """Extended mock transport with helper methods."""

    @classmethod
    def with_responses(
        cls,
        responses: dict[str, dict[str, Any]],
    ) -> "MockTransport":
        """
        Create a mock transport with predefined responses.

        Args:
            responses: Dict mapping URL patterns to response data
                       Keys can be "POST /path" or just "/path"

        Example:
            transport = MockTransport.with_responses({
                "POST /oauth/token": {"access_token": "..."},
                "/user/v2/user/auth0%7Ctest/appliances": {"appliances": []},
            })
        """

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            method = request.method

            # Try method + path first
            key = f"{method} {path}"
            if key in responses:
                return httpx.Response(200, json=responses[key])

            # Try just path
            if path in responses:
                return httpx.Response(200, json=responses[path])

            # Check for partial matches
            for pattern, data in responses.items():
                if pattern in path or path in pattern:
                    return httpx.Response(200, json=data)

            return httpx.Response(404, json={"error": "Not found"})

        return cls(handler)

    @classmethod
    def oauth_success(cls, token_response: dict[str, Any]) -> "MockTransport":
        """Create a mock transport that returns successful OAuth responses."""
        return cls.with_responses(
            {
                "POST /oauth/token": token_response,
            }
        )

    @classmethod
    def with_error(cls, status_code: int, error: str = "Error") -> "MockTransport":
        """Create a mock transport that returns an error."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, json={"error": error})

        return cls(handler)


def create_mock_client(
    responses: dict[str, dict[str, Any]] | None = None,
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> httpx.AsyncClient:
    """
    Create a mock async HTTP client.

    Args:
        responses: Dict mapping URL patterns to response data
        handler: Custom request handler function

    Returns:
        Configured httpx.AsyncClient
    """
    if handler:
        transport = httpx.MockTransport(handler)
    elif responses:
        transport = MockTransport.with_responses(responses)
    else:
        transport = MockTransport.with_responses({})

    return httpx.AsyncClient(transport=transport)
