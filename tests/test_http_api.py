"""Tests for the HTTP API client."""

import logging
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from sagecoffee.client import SageCoffeeClient
from sagecoffee.http_api import DEFAULT_APP, BrevilleApiClient, SyncBrevilleApiClient
from tests.mocks.http_mock import create_mock_client


class TestBrevilleApiClient:
    """Tests for BrevilleApiClient."""

    @pytest.fixture
    def mock_get_token(self) -> AsyncMock:
        """Create a mock get_id_token function."""
        mock = AsyncMock(return_value="test_id_token")
        return mock

    @pytest.fixture
    def mock_refresh(self) -> AsyncMock:
        """Create a mock refresh callback."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_wake(
        self,
        mock_get_token: AsyncMock,
        mock_refresh: AsyncMock,
    ) -> None:
        """Test wake command."""
        http_client = create_mock_client(
            {
                "/appliance/v1/appliances/ABC123/set-coffeeParams": {"success": True},
            }
        )

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            refresh_token_callback=mock_refresh,
            http_client=http_client,
        )

        result = await client.wake("ABC123")

        assert result == {"success": True}
        mock_get_token.assert_called()

    @pytest.mark.asyncio
    async def test_sleep(
        self,
        mock_get_token: AsyncMock,
        mock_refresh: AsyncMock,
    ) -> None:
        """Test sleep command."""
        http_client = create_mock_client(
            {
                "/appliance/v1/appliances/ABC123/set-coffeeParams": {"success": True},
            }
        )

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            refresh_token_callback=mock_refresh,
            http_client=http_client,
        )

        result = await client.sleep("ABC123")

        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_list_appliances(
        self,
        mock_get_token: AsyncMock,
        sample_appliances_response: dict,
    ) -> None:
        """Test listing appliances."""

        def handler(request: httpx.Request) -> httpx.Response:
            # Check that URL is correctly encoded
            if "auth0%7Ctest" in str(request.url):
                return httpx.Response(200, json=sample_appliances_response)
            return httpx.Response(404, json={"error": "Not found"})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        result = await client.list_appliances("auth0|test")

        assert len(result) == 2
        assert result[0].serial_number == "A1SKAESA251400639"
        assert result[1].serial_number == "B2TEST123456789"

    @pytest.mark.asyncio
    async def test_list_appliances_logs_response_keys(
        self,
        mock_get_token: AsyncMock,
        sample_appliances_response: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that a populated response logs its top-level keys and no warning."""
        http_client = create_mock_client(
            handler=lambda request: httpx.Response(200, json=sample_appliances_response)
        )

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        with caplog.at_level(logging.DEBUG, logger="sagecoffee.http_api"):
            result = await client.list_appliances("auth0|test")

        assert len(result) == 2
        assert "Appliance list response keys: ['appliances', 'ownedModels']" in caplog.text
        assert "no 'appliances' key" not in caplog.text

    @pytest.mark.asyncio
    async def test_list_appliances_empty_list(
        self,
        mock_get_token: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that an empty appliances list is not treated as an unexpected shape."""
        http_client = create_mock_client(
            handler=lambda request: httpx.Response(200, json={"appliances": [], "ownedModels": []})
        )

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        with caplog.at_level(logging.DEBUG, logger="sagecoffee.http_api"):
            result = await client.list_appliances("auth0|test")

        assert result == []
        assert "Appliance list response keys: ['appliances', 'ownedModels']" in caplog.text
        assert "no 'appliances' key" not in caplog.text

    @pytest.mark.asyncio
    async def test_list_appliances_missing_key_warns(
        self,
        mock_get_token: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that a response with no appliances key logs a warning."""
        http_client = create_mock_client(
            handler=lambda request: httpx.Response(200, json={"devices": [], "id_token": "secret"})
        )

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        with caplog.at_level(logging.DEBUG, logger="sagecoffee.http_api"):
            result = await client.list_appliances("auth0|test")

        assert result == []
        assert "Appliance list response keys: ['devices', 'id_token']" in caplog.text
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "no 'appliances' key" in warnings[0].getMessage()
        # The body is logged for diagnosis, but token-like values are redacted.
        assert "'devices': []" in warnings[0].getMessage()
        assert "secret" not in warnings[0].getMessage()

    @pytest.mark.asyncio
    async def test_request_logs_response_status(
        self,
        mock_get_token: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that request logs the response status and size at debug level."""
        http_client = create_mock_client(handler=lambda request: httpx.Response(200, json={"a": 1}))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        with caplog.at_level(logging.DEBUG, logger="sagecoffee.http_api"):
            await client.raw_get("/some/path")

        assert "-> 200 (" in caplog.text

    @pytest.mark.asyncio
    async def test_retry_on_401(
        self,
        mock_get_token: AsyncMock,
        mock_refresh: AsyncMock,
    ) -> None:
        """Test that 401 triggers refresh and retry."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                return httpx.Response(401, json={"error": "Unauthorized"})
            return httpx.Response(200, json={"success": True})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            refresh_token_callback=mock_refresh,
            http_client=http_client,
        )

        result = await client.wake("ABC123")

        assert result == {"success": True}
        assert call_count == 2
        mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_headers(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test that correct headers are sent."""
        captured_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, json={})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            app="testApp",
            http_client=http_client,
        )

        await client.wake("ABC123")

        assert captured_headers.get("sf-id-token") == "test_id_token"
        assert captured_headers.get("app") == "testApp"
        assert captured_headers.get("content-type") == "application/json"

    @pytest.mark.asyncio
    async def test_app_none_falls_back_to_default(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test that app=None sends the default identifier instead of a None header."""
        captured_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, json={})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            app=None,
            http_client=http_client,
        )

        await client.wake("ABC123")

        assert captured_headers.get("app") == DEFAULT_APP

    @pytest.mark.asyncio
    async def test_set_coffee_params(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test set_coffee_params with custom payload."""
        captured_body = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = request.content.decode()
            return httpx.Response(200, json={"success": True})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        await client.set_coffee_params("ABC123", {"state": "ready", "custom": "value"})

        import json

        body = json.loads(captured_body)
        assert body["state"] == "ready"
        assert body["custom"] == "value"
    @pytest.mark.asyncio
    async def test_set_volume(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test set_volume command."""
        captured_body = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = request.content.decode()
            return httpx.Response(200, json={"success": True})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        result = await client.set_volume("ABC123", 50)

        import json

        body = json.loads(captured_body)
        assert body["cfg"]["vol"] == 50
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_set_brightness(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test set_brightness command."""
        captured_body = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = request.content.decode()
            return httpx.Response(200, json={"success": True})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        result = await client.set_brightness("ABC123", 75)

        import json

        body = json.loads(captured_body)
        assert body["cfg"]["brightness"] == 75
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_set_color_theme(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test set_color_theme command."""
        captured_body = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = request.content.decode()
            return httpx.Response(200, json={"success": True})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        result = await client.set_color_theme("ABC123", "dark")

        import json

        body = json.loads(captured_body)
        assert body["cfg"]["theme"] == "dark"
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_set_appliance_name(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test set_appliance_name command."""
        captured_body = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = request.content.decode()
            return httpx.Response(200, json={"success": True})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        result = await client.set_appliance_name("ABC123", "Kitchen Brewer")

        import json

        body = json.loads(captured_body)
        assert body["applianceName"] == "Kitchen Brewer"
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_set_work_light_brightness(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test set_work_light_brightness command."""
        captured_body = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = request.content.decode()
            return httpx.Response(200, json={"success": True})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        result = await client.set_work_light_brightness("ABC123", 100)

        import json

        body = json.loads(captured_body)
        assert body["cfg"]["work_light_brightness"] == 100
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_set_wake_schedule(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test set_wake_schedule command."""
        captured_body = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = request.content.decode()
            return httpx.Response(200, json={"success": True})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        result = await client.set_wake_schedule("ABC123", "20 6 * * 1-5", enabled=True)

        import json

        body = json.loads(captured_body)
        assert body["cfg"]["wake_schedule"][0]["cron"] == "20 6 * * 1-5"
        assert body["cfg"]["wake_schedule"][0]["on"] is True
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_disable_wake_schedule(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test disable_wake_schedule command."""
        captured_body = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = request.content.decode()
            return httpx.Response(200, json={"success": True})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        client = BrevilleApiClient(
            get_id_token=mock_get_token,
            http_client=http_client,
        )

        result = await client.disable_wake_schedule("ABC123")

        import json

        body = json.loads(captured_body)
        assert body["cfg"]["wake_schedule"] == []
        assert result == {"success": True}

class TestSyncBrevilleApiClient:
    """Tests for SyncBrevilleApiClient."""

    def test_app_none_falls_back_to_default(self) -> None:
        """Test that app=None yields the default identifier in headers."""
        client = SyncBrevilleApiClient(id_token="test_id_token", app=None)

        headers = client._get_headers()

        assert headers["app"] == DEFAULT_APP

    def test_list_appliances_missing_key_warns(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that the sync client also warns on a response with no appliances key."""
        client = SyncBrevilleApiClient(id_token="test_id_token")

        def fake_request(*args: Any, **kwargs: Any) -> dict:
            return {"devices": []}

        monkeypatch.setattr(client, "request", fake_request)

        with caplog.at_level(logging.DEBUG, logger="sagecoffee.http_api"):
            result = client.list_appliances("auth0|test")

        assert result == []
        assert "Appliance list response keys: ['devices']" in caplog.text
        assert "no 'appliances' key" in caplog.text

    def test_list_appliances_empty_list(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that the sync client does not warn on a legitimately empty account."""
        client = SyncBrevilleApiClient(id_token="test_id_token")

        def fake_request(*args: Any, **kwargs: Any) -> dict:
            return {"appliances": []}

        monkeypatch.setattr(client, "request", fake_request)

        with caplog.at_level(logging.DEBUG, logger="sagecoffee.http_api"):
            result = client.list_appliances("auth0|test")

        assert result == []
        assert "no 'appliances' key" not in caplog.text


class TestSageCoffeeClientApp:
    """Tests for app identifier handling in SageCoffeeClient."""

    def test_app_none_falls_back_to_default(self) -> None:
        """Test that app=None is normalised to the default identifier."""
        client = SageCoffeeClient(client_id="test_client", refresh_token="test_refresh", app=None)

        assert client._app == DEFAULT_APP

    def test_app_is_preserved(self) -> None:
        """Test that an explicit app identifier is preserved."""
        client = SageCoffeeClient(
            client_id="test_client", refresh_token="test_refresh", app="brevilleCoffee"
        )

        assert client._app == "brevilleCoffee"
