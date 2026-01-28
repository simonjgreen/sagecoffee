"""WebSocket client for Breville/Sage appliance state streaming."""

import asyncio
import json
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from sagecoffee.logging import get_logger, redact_dict
from sagecoffee.models import (
    AddApplianceMessage,
    DeviceState,
    PingMessage,
    StateReport,
)

logger = get_logger("ws_client")

# WebSocket endpoint
WS_URL = "wss://iot-api-ws.breville.com/applianceProxy"
WS_ORIGIN = "https://iot-api-ws.breville.com"

# Keepalive settings
PING_INTERVAL = 30  # seconds
PING_TIMEOUT = 10  # seconds

# Reconnect settings
RECONNECT_BASE_DELAY = 1  # seconds
RECONNECT_MAX_DELAY = 30  # seconds
RECONNECT_JITTER = 0.5  # fraction of delay to add as jitter


class BrevilleWsClient:
    """
    WebSocket client for streaming appliance state updates.

    Handles connection, keepalive, and automatic reconnection.
    """

    def __init__(
        self,
        get_id_token: Callable[[], Awaitable[str]],
        refresh_token_callback: Callable[[], Awaitable[None]] | None = None,
        on_state: Callable[[DeviceState], None] | None = None,
        on_raw_message: Callable[[dict[str, Any]], None] | None = None,
        ping_interval: int = PING_INTERVAL,
        ssl_context: Any | None = None,
    ):
        """
        Initialize the WebSocket client.

        Args:
            get_id_token: Async callable that returns the current id_token
            refresh_token_callback: Async callable to refresh tokens
            on_state: Callback for state updates
            on_raw_message: Callback for all messages
            ping_interval: Seconds between ping messages
            ssl_context: Optional pre-configured SSL context
        """
        self._get_id_token = get_id_token
        self._refresh_callback = refresh_token_callback
        self._on_state = on_state
        self._on_raw_message = on_raw_message
        self._ping_interval = ping_interval
        self._ssl_context = ssl_context

        self._ws: ClientConnection | None = None
        self._running = False
        self._reconnect_delay = RECONNECT_BASE_DELAY

        # State cache per serial number
        self._state_cache: dict[str, DeviceState] = {}

        # Registered appliances
        self._appliances: list[tuple[str, str, str]] = []  # (serial, app, model)

        # Tasks
        self._ping_task: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._ws is not None and self._ws.state.name == "OPEN"

    def get_last_state(self, serial: str | None = None) -> DeviceState | None:
        """
        Get the last known state for an appliance.

        Args:
            serial: Appliance serial number (or None for first appliance)

        Returns:
            Last known DeviceState, or None if no state received
        """
        if serial:
            return self._state_cache.get(serial)

        # Return first available state
        if self._state_cache:
            return next(iter(self._state_cache.values()))
        return None

    def get_all_states(self) -> dict[str, DeviceState]:
        """Get all cached appliance states."""
        return dict(self._state_cache)

    async def _connect(self) -> None:
        """Establish WebSocket connection."""
        id_token = await self._get_id_token()

        headers = {
            "sf-id-token": id_token,
            "Origin": WS_ORIGIN,
        }

        logger.info("Connecting to WebSocket")
        # Use provided SSL context or let websockets handle it
        connect_kwargs = {
            "additional_headers": headers,
            "ping_interval": None,  # We handle our own pings
            "ping_timeout": None,
        }
        if self._ssl_context is not None:
            connect_kwargs["ssl"] = self._ssl_context

        self._ws = await websockets.connect(WS_URL, **connect_kwargs)
        logger.info("WebSocket connected")

        # Reset reconnect delay on successful connect
        self._reconnect_delay = RECONNECT_BASE_DELAY

    async def add_appliance(
        self,
        serial: str,
        app: str = "sageCoffee",
        model: str = "BES995",
    ) -> None:
        """
        Register an appliance to receive state updates.

        Args:
            serial: Appliance serial number
            app: App identifier
            model: Appliance model
        """
        # Store for reconnection
        appliance = (serial, app, model)
        if appliance not in self._appliances:
            self._appliances.append(appliance)

        if not self._ws:
            logger.warning("Cannot add appliance: not connected")
            return

        message = AddApplianceMessage(
            serial_number=serial,
            app=app,
            model=model,
        )

        payload = message.model_dump(by_alias=True)
        logger.debug("Sending addAppliance: %s", redact_dict(payload))

        await self._ws.send(json.dumps(payload))

    async def _send_ping(self) -> None:
        """Send a ping message."""
        if not self._ws:
            return

        message = PingMessage()
        await self._ws.send(json.dumps(message.model_dump()))
        logger.debug("Sent ping")

    async def _ping_loop(self) -> None:
        """Background task to send periodic pings."""
        while self._running and self._ws:
            try:
                await asyncio.sleep(self._ping_interval)
                if self._ws:
                    await self._send_ping()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Ping error: %s", e)

    def _handle_message(self, data: dict[str, Any]) -> None:
        """
        Handle a received message.

        Args:
            data: Parsed JSON message
        """
        # Call raw message callback
        if self._on_raw_message:
            self._on_raw_message(data)

        message_type = data.get("messageType")

        if message_type == "pong":
            logger.debug("Received pong")
            return

        if message_type == "stateReport":
            try:
                report = StateReport.model_validate(data)
                state = DeviceState.from_state_report(report)

                # Update cache
                self._state_cache[report.serial_number] = state

                logger.debug(
                    "State update for %s: %s",
                    report.serial_number,
                    state.reported_state,
                )

                # Call state callback
                if self._on_state:
                    self._on_state(state)

            except Exception as e:
                logger.warning("Failed to parse stateReport: %s", e)
            return

        # Check for forbidden/error messages
        if data.get("message") == "Forbidden":
            logger.warning("Received Forbidden message, re-registering appliances")
            # Will be handled by the listen loop
            return

        logger.debug("Unknown message type: %s", message_type)

    async def _receive_loop(self) -> AsyncIterator[dict[str, Any]]:
        """
        Receive messages from the WebSocket.

        Yields:
            Parsed JSON messages
        """
        if not self._ws:
            return

        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    message = message.decode("utf-8")

                try:
                    data = json.loads(message)
                    self._handle_message(data)
                    yield data
                except json.JSONDecodeError as e:
                    logger.warning("Invalid JSON message: %s", e)

        except websockets.ConnectionClosed as e:
            logger.info("WebSocket closed: %s", e)
            raise
        except Exception as e:
            logger.error("WebSocket error: %s", e)
            raise

    async def _reconnect_with_backoff(self) -> None:
        """Reconnect with exponential backoff and jitter."""
        # Add jitter
        jitter = random.uniform(0, RECONNECT_JITTER * self._reconnect_delay)
        delay = self._reconnect_delay + jitter

        logger.info("Reconnecting in %.1f seconds", delay)
        await asyncio.sleep(delay)

        # Increase delay for next time (exponential backoff)
        self._reconnect_delay = min(
            self._reconnect_delay * 2,
            RECONNECT_MAX_DELAY,
        )

        # Refresh token if we have a callback
        if self._refresh_callback:
            try:
                await self._refresh_callback()
            except Exception as e:
                logger.warning("Token refresh failed: %s", e)

        await self._connect()

        # Re-register all appliances
        for serial, app, model in self._appliances:
            await self.add_appliance(serial, app, model)

    async def connect(self) -> None:
        """Connect to the WebSocket server."""
        await self._connect()

    async def disconnect(self) -> None:
        """Disconnect from the WebSocket server."""
        self._running = False

        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        logger.info("WebSocket disconnected")

    async def listen(self, auto_reconnect: bool = True) -> AsyncIterator[dict[str, Any]]:
        """
        Listen for messages from the WebSocket.

        This is the main entry point for streaming state updates.
        It handles reconnection automatically.

        Args:
            auto_reconnect: Whether to automatically reconnect on disconnect

        Yields:
            Parsed JSON messages
        """
        self._running = True

        while self._running:
            try:
                # Connect if not connected
                if not self._ws:
                    await self._connect()

                    # Register all appliances
                    for serial, app, model in self._appliances:
                        await self.add_appliance(serial, app, model)

                # Start ping task
                self._ping_task = asyncio.create_task(self._ping_loop())

                # Receive messages
                async for message in self._receive_loop():
                    yield message

            except websockets.ConnectionClosed:
                self._ws = None
                if self._ping_task:
                    self._ping_task.cancel()

                if not auto_reconnect or not self._running:
                    break

                await self._reconnect_with_backoff()

            except Exception as e:
                logger.error("Unexpected error: %s", e)
                self._ws = None
                if self._ping_task:
                    self._ping_task.cancel()

                if not auto_reconnect or not self._running:
                    raise

                await self._reconnect_with_backoff()

    async def listen_states(self, auto_reconnect: bool = True) -> AsyncIterator[DeviceState]:
        """
        Listen for state updates only.

        Convenience method that yields only DeviceState objects.

        Args:
            auto_reconnect: Whether to automatically reconnect

        Yields:
            DeviceState objects
        """
        async for message in self.listen(auto_reconnect):
            if message.get("messageType") == "stateReport":
                try:
                    report = StateReport.model_validate(message)
                    yield DeviceState.from_state_report(report)
                except Exception as e:
                    logger.warning("Failed to parse state report: %s", e)

    async def send_raw(self, message: dict[str, Any]) -> None:
        """
        Send a raw message to the WebSocket.

        Args:
            message: Message to send as dictionary
        """
        if not self._ws:
            raise RuntimeError("Not connected")

        await self._ws.send(json.dumps(message))
        logger.debug("Sent raw message: %s", redact_dict(message))

    async def __aenter__(self) -> "BrevilleWsClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.disconnect()
