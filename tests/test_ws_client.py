"""Tests for the WebSocket client."""

import json
from unittest.mock import AsyncMock

import pytest

from sagecoffee.models import DeviceState
from sagecoffee.ws_client import BrevilleWsClient
from tests.mocks.ws_mock import MockWebSocket, MockWebSocketServer


class TestBrevilleWsClient:
    """Tests for BrevilleWsClient."""

    @pytest.fixture
    def mock_get_token(self) -> AsyncMock:
        """Create a mock get_id_token function."""
        return AsyncMock(return_value="test_id_token")

    @pytest.fixture
    def mock_refresh(self) -> AsyncMock:
        """Create a mock refresh callback."""
        return AsyncMock()

    @pytest.fixture
    def ws_server(self) -> MockWebSocketServer:
        """Create a mock WebSocket server."""
        return MockWebSocketServer()

    def test_get_last_state_empty(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test get_last_state returns None when no state received."""
        client = BrevilleWsClient(get_id_token=mock_get_token)
        assert client.get_last_state() is None

    def test_is_connected_initially_false(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test is_connected is False initially."""
        client = BrevilleWsClient(get_id_token=mock_get_token)
        assert not client.is_connected

    def test_handle_state_report(
        self,
        mock_get_token: AsyncMock,
        sample_state_report: dict,
    ) -> None:
        """Test handling a state report message."""
        states_received: list[DeviceState] = []

        def on_state(state: DeviceState) -> None:
            states_received.append(state)

        client = BrevilleWsClient(
            get_id_token=mock_get_token,
            on_state=on_state,
        )

        # Directly call the handler
        client._handle_message(sample_state_report)

        assert len(states_received) == 1
        assert states_received[0].serial_number == "A1SKAESA251400639"
        assert states_received[0].reported_state == "ready"

        # Check cache was updated
        cached = client.get_last_state("A1SKAESA251400639")
        assert cached is not None
        assert cached.reported_state == "ready"

    def test_handle_pong(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test handling a pong message."""
        client = BrevilleWsClient(get_id_token=mock_get_token)

        # Should not raise
        client._handle_message({"messageType": "pong"})

    def test_handle_forbidden(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test handling a forbidden message."""
        client = BrevilleWsClient(get_id_token=mock_get_token)

        # Should not raise (just logs warning)
        client._handle_message({"message": "Forbidden"})

    def test_add_appliance_stored(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test that add_appliance stores appliance info."""
        client = BrevilleWsClient(get_id_token=mock_get_token)

        # Manually add without connection (tests storage)
        client._appliances.append(("ABC123", "sageCoffee", "BES995"))

        assert len(client._appliances) == 1
        assert client._appliances[0] == ("ABC123", "sageCoffee", "BES995")

    def test_get_all_states(
        self,
        mock_get_token: AsyncMock,
        sample_state_report: dict,
    ) -> None:
        """Test getting all cached states."""
        client = BrevilleWsClient(get_id_token=mock_get_token)

        # Add some states
        client._handle_message(sample_state_report)

        # Modify and add another
        report2 = dict(sample_state_report)
        report2["serialNumber"] = "OTHER123"
        client._handle_message(report2)

        states = client.get_all_states()
        assert len(states) == 2
        assert "A1SKAESA251400639" in states
        assert "OTHER123" in states

    def test_raw_message_callback(
        self,
        mock_get_token: AsyncMock,
    ) -> None:
        """Test that raw message callback is called."""
        raw_messages: list[dict] = []

        def on_raw(msg: dict) -> None:
            raw_messages.append(msg)

        client = BrevilleWsClient(
            get_id_token=mock_get_token,
            on_raw_message=on_raw,
        )

        client._handle_message({"test": "message"})

        assert len(raw_messages) == 1
        assert raw_messages[0] == {"test": "message"}


class TestMockWebSocketServer:
    """Tests for the mock WebSocket server."""

    def test_add_state_report(self) -> None:
        """Test adding a state report to mock server."""
        server = MockWebSocketServer()
        server.add_state_report("ABC123", state="ready")

        assert len(server._messages_to_send) == 1
        msg = server._messages_to_send[0]
        assert msg["serialNumber"] == "ABC123"
        assert msg["messageType"] == "stateReport"
        assert msg["data"]["reported"]["state"] == "ready"

    def test_create_connection(self) -> None:
        """Test creating a mock connection."""
        server = MockWebSocketServer()
        server.add_pong()

        ws = server.create_connection()

        assert ws is not None
        assert len(server._connections) == 1

    @pytest.mark.asyncio
    async def test_mock_websocket_send_receive(self) -> None:
        """Test mock WebSocket send and receive."""
        messages = [
            {"messageType": "pong"},
            {"serialNumber": "ABC", "messageType": "stateReport", "data": {}},
        ]

        ws = MockWebSocket(messages=messages)

        # Send a message
        await ws.send('{"action":"ping"}')
        assert len(ws._sent_messages) == 1

        # Receive messages
        received = []
        async for msg in ws:
            received.append(json.loads(msg))

        assert len(received) == 2
        assert received[0]["messageType"] == "pong"
