"""Mock WebSocket server for testing."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any


class MockWebSocket:
    """Mock WebSocket connection for testing."""

    def __init__(
        self,
        messages: list[dict[str, Any]] | None = None,
        on_send: Callable[[dict[str, Any]], None] | None = None,
    ):
        """
        Initialize mock WebSocket.

        Args:
            messages: List of messages to yield
            on_send: Callback when client sends a message
        """
        self._messages = messages or []
        self._message_index = 0
        self._on_send = on_send
        self._sent_messages: list[dict[str, Any]] = []
        self._closed = False

        # For state simulation
        self._state = "OPEN"

    @property
    def state(self) -> Any:
        """Return mock state object."""

        class State:
            def __init__(self, name: str):
                self.name = name

        return State(self._state)

    async def send(self, message: str) -> None:
        """Record a sent message."""
        if self._closed:
            raise RuntimeError("WebSocket is closed")

        data = json.loads(message)
        self._sent_messages.append(data)

        if self._on_send:
            self._on_send(data)

    async def recv(self) -> str:
        """Receive the next message."""
        if self._closed:
            raise RuntimeError("WebSocket is closed")

        if self._message_index >= len(self._messages):
            # Simulate waiting forever
            await asyncio.sleep(10)
            raise asyncio.CancelledError()

        message = self._messages[self._message_index]
        self._message_index += 1
        return json.dumps(message)

    async def close(self) -> None:
        """Close the connection."""
        self._closed = True
        self._state = "CLOSED"

    def __aiter__(self) -> AsyncIterator[str]:
        """Iterate over messages."""
        return self

    async def __anext__(self) -> str:
        """Get next message."""
        if self._closed or self._message_index >= len(self._messages):
            raise StopAsyncIteration

        message = self._messages[self._message_index]
        self._message_index += 1
        return json.dumps(message)


class MockWebSocketServer:
    """Mock WebSocket server for integration testing."""

    def __init__(self):
        """Initialize the mock server."""
        self._connections: list[MockWebSocket] = []
        self._messages_to_send: list[dict[str, Any]] = []
        self._received_messages: list[dict[str, Any]] = []

    def add_message(self, message: dict[str, Any]) -> None:
        """Add a message to be sent to connected clients."""
        self._messages_to_send.append(message)

    def add_state_report(
        self,
        serial: str,
        state: str = "ready",
        boilers: list[dict[str, float]] | None = None,
    ) -> None:
        """Add a state report message."""
        self.add_message(
            {
                "serialNumber": serial,
                "messageType": "stateReport",
                "version": 1,
                "data": {
                    "reported": {
                        "state": state,
                        "boiler": boilers or [],
                    },
                    "desired": {
                        "state": state,
                    },
                },
            }
        )

    def add_pong(self) -> None:
        """Add a pong response."""
        self.add_message({"messageType": "pong"})

    def add_forbidden(self) -> None:
        """Add a forbidden response."""
        self.add_message({"message": "Forbidden"})

    def create_connection(self) -> MockWebSocket:
        """Create a new mock WebSocket connection."""

        def on_send(data: dict[str, Any]) -> None:
            self._received_messages.append(data)

            # Auto-respond to ping
            if data.get("action") == "ping":
                self._messages_to_send.insert(0, {"messageType": "pong"})

        ws = MockWebSocket(
            messages=list(self._messages_to_send),
            on_send=on_send,
        )
        self._connections.append(ws)
        return ws

    @property
    def received_messages(self) -> list[dict[str, Any]]:
        """Get all received messages."""
        return self._received_messages

    def get_add_appliance_messages(self) -> list[dict[str, Any]]:
        """Get all addAppliance messages received."""
        return [m for m in self._received_messages if m.get("action") == "addAppliance"]
