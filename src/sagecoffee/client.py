"""High-level client facade for Sage Coffee library."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from sagecoffee.auth import AuthClient
from sagecoffee.http_api import BrevilleApiClient
from sagecoffee.logging import get_logger
from sagecoffee.models import Appliance, DeviceState, TokenSet
from sagecoffee.store import ConfigStore
from sagecoffee.ws_client import BrevilleWsClient

logger = get_logger("client")


class TokenManager:
    """
    Manages OAuth tokens with automatic refresh.

    Provides thread-safe token access with refresh locking
    to prevent concurrent refresh stampedes.
    """

    def __init__(
        self,
        auth_client: AuthClient,
        initial_tokens: TokenSet | None = None,
        store: ConfigStore | None = None,
        skew_seconds: int = 60,
    ):
        """
        Initialize the token manager.

        Args:
            auth_client: AuthClient for refreshing tokens
            initial_tokens: Optional initial token set
            store: Optional ConfigStore to persist tokens
            skew_seconds: Refresh this many seconds before expiry
        """
        self._auth_client = auth_client
        self._tokens = initial_tokens
        self._store = store
        self._skew_seconds = skew_seconds
        self._lock = asyncio.Lock()

    @property
    def tokens(self) -> TokenSet | None:
        """Get the current token set."""
        return self._tokens

    @tokens.setter
    def tokens(self, value: TokenSet) -> None:
        """Set the token set and persist if store is configured."""
        self._tokens = value
        if self._store and value.refresh_token:
            self._store.save_token_set(value)

    def has_valid_tokens(self) -> bool:
        """Check if we have non-expired tokens."""
        if not self._tokens:
            return False
        return not self._tokens.is_expired(self._skew_seconds)

    async def get_id_token(self) -> str:
        """
        Get a valid id_token, refreshing if necessary.

        Returns:
            Valid id_token

        Raises:
            ValueError: If no tokens are available
        """
        async with self._lock:
            if not self._tokens:
                raise ValueError("No tokens available")

            if self._tokens.is_expired(self._skew_seconds):
                logger.info("Token expired, refreshing")
                await self._refresh()

            if not self._tokens.id_token:
                raise ValueError("No id_token available after refresh")

            return self._tokens.id_token

    async def get_access_token(self) -> str:
        """
        Get a valid access_token, refreshing if necessary.

        Returns:
            Valid access_token

        Raises:
            ValueError: If no tokens are available
        """
        async with self._lock:
            if not self._tokens:
                raise ValueError("No tokens available")

            if self._tokens.is_expired(self._skew_seconds):
                logger.info("Token expired, refreshing")
                await self._refresh()

            if not self._tokens.access_token:
                raise ValueError("No access_token available after refresh")

            return self._tokens.access_token

    async def refresh(self) -> TokenSet:
        """
        Force a token refresh.

        Returns:
            Fresh TokenSet
        """
        async with self._lock:
            await self._refresh()
            if not self._tokens:
                raise ValueError("Refresh failed")
            return self._tokens

    async def _refresh(self) -> None:
        """Internal refresh (must hold lock)."""
        if not self._tokens or not self._tokens.refresh_token:
            raise ValueError("No refresh_token available")

        new_tokens = await self._auth_client.refresh(self._tokens.refresh_token)
        self.tokens = new_tokens
        logger.info("Tokens refreshed successfully")

    def auth0_sub(self) -> str | None:
        """Get the Auth0 subject from current tokens."""
        if not self._tokens:
            return None
        return self._tokens.auth0_sub()


class SageCoffeeClient:
    """
    High-level client for controlling Sage/Breville coffee machines.

    Combines authentication, REST API, and WebSocket functionality
    into a single convenient interface.
    """

    def __init__(
        self,
        client_id: str,
        refresh_token: str | None = None,
        tokens: TokenSet | None = None,
        store: ConfigStore | None = None,
        app: str = "sageCoffee",
        httpx_client: Any | None = None,
        ssl_context: Any | None = None,
    ):
        """
        Initialize the Sage Coffee client.

        Args:
            client_id: OAuth client ID
            refresh_token: Optional refresh token (creates TokenSet if provided)
            tokens: Optional existing TokenSet
            store: Optional ConfigStore for persistence
            app: App identifier for API requests
            httpx_client: Optional pre-configured httpx.AsyncClient
            ssl_context: Optional pre-configured SSL context for WebSocket
        """
        self._client_id = client_id
        self._app = app
        self._store = store
        self._httpx_client = httpx_client
        self._ssl_context = ssl_context

        # Set up auth client
        self._auth_client = AuthClient(client_id, httpx_client)

        # Set up tokens
        if tokens:
            initial_tokens = tokens
        elif refresh_token:
            initial_tokens = TokenSet(refresh_token=refresh_token)
        elif store:
            initial_tokens = store.get_token_set()
        else:
            initial_tokens = None

        # Set up token manager
        self._token_manager = TokenManager(
            self._auth_client,
            initial_tokens,
            store,
        )

        # Set up API client (lazy)
        self._api_client: BrevilleApiClient | None = None

        # Set up WS client (lazy)
        self._ws_client: BrevilleWsClient | None = None

        # Discovered appliances
        self._appliances: list[Appliance] | None = None

    @classmethod
    def from_config(cls, store: ConfigStore) -> "SageCoffeeClient":
        """
        Create a client from a ConfigStore.

        Args:
            store: ConfigStore with credentials

        Returns:
            Configured SageCoffeeClient

        Raises:
            ValueError: If store is not configured
        """
        if not store.is_configured():
            raise ValueError("ConfigStore is not configured (missing client_id or refresh_token)")

        return cls(
            client_id=store.client_id,  # type: ignore
            store=store,
            app=store.app,
        )

    @property
    def token_manager(self) -> TokenManager:
        """Get the token manager."""
        return self._token_manager

    @property
    def tokens(self) -> TokenSet | None:
        """Get the current tokens."""
        return self._token_manager.tokens

    def _get_api_client(self) -> BrevilleApiClient:
        """Get or create the API client."""
        if self._api_client is None:
            self._api_client = BrevilleApiClient(
                get_id_token=self._token_manager.get_id_token,
                refresh_token_callback=self._token_manager.refresh,
                app=self._app,
                http_client=self._httpx_client,
            )
        return self._api_client

    def _get_ws_client(self) -> BrevilleWsClient:
        """Get or create the WebSocket client."""
        if self._ws_client is None:
            self._ws_client = BrevilleWsClient(
                get_id_token=self._token_manager.get_id_token,
                refresh_token_callback=self._token_manager.refresh,
                ssl_context=self._ssl_context,
            )
        return self._ws_client

    async def close(self) -> None:
        """Close all connections."""
        if self._api_client:
            await self._api_client.close()
            self._api_client = None

        if self._ws_client:
            await self._ws_client.disconnect()
            self._ws_client = None

        await self._auth_client.close()

    # Authentication methods

    async def bootstrap(self, username: str, password: str) -> TokenSet:
        """
        Bootstrap authentication with username/password.

        This should only be used once to obtain a refresh_token.
        After that, use the refresh_token for authentication.

        Args:
            username: User's email address
            password: User's password

        Returns:
            TokenSet with tokens
        """
        tokens = await self._auth_client.password_realm_login(username, password)
        self._token_manager.tokens = tokens
        logger.info("Bootstrap successful")
        return tokens

    async def refresh_tokens(self) -> TokenSet:
        """
        Refresh the current tokens.

        Returns:
            Fresh TokenSet
        """
        return await self._token_manager.refresh()

    # Appliance discovery

    async def list_appliances(self) -> list[Appliance]:
        """
        List all appliances for the current user.

        Returns:
            List of Appliance objects
        """
        sub = self._token_manager.auth0_sub()
        if not sub:
            # Need to refresh to get id_token with sub
            await self._token_manager.refresh()
            sub = self._token_manager.auth0_sub()
            if not sub:
                raise ValueError("Could not determine Auth0 user ID")

        api = self._get_api_client()
        self._appliances = await api.list_appliances(sub)
        return self._appliances

    async def get_appliance(self, serial: str | None = None) -> Appliance:
        """
        Get a specific appliance, or the first one if serial not specified.

        Args:
            serial: Optional serial number

        Returns:
            Appliance object

        Raises:
            ValueError: If no appliances found or serial not found
        """
        if self._appliances is None:
            await self.list_appliances()

        if not self._appliances:
            raise ValueError("No appliances found")

        if serial:
            for appliance in self._appliances:
                if appliance.serial_number == serial:
                    return appliance
            raise ValueError(f"Appliance {serial} not found")

        return self._appliances[0]

    # REST API methods

    async def wake(self, serial: str | None = None) -> dict[str, Any]:
        """
        Wake up an appliance.

        Args:
            serial: Appliance serial (auto-selects if only one appliance)

        Returns:
            API response
        """
        appliance = await self.get_appliance(serial)
        api = self._get_api_client()
        return await api.wake(appliance.serial_number)

    async def sleep(self, serial: str | None = None) -> dict[str, Any]:
        """
        Put an appliance to sleep.

        Args:
            serial: Appliance serial (auto-selects if only one appliance)

        Returns:
            API response
        """
        appliance = await self.get_appliance(serial)
        api = self._get_api_client()
        return await api.sleep(appliance.serial_number)

    async def set_state(self, state: str, serial: str | None = None) -> dict[str, Any]:
        """
        Set the appliance state.

        Args:
            state: State to set (e.g., "ready", "asleep")
            serial: Appliance serial (auto-selects if only one appliance)

        Returns:
            API response
        """
        appliance = await self.get_appliance(serial)
        api = self._get_api_client()
        return await api.set_coffee_params(appliance.serial_number, {"state": state})

    async def set_coffee_params(
        self,
        params: dict[str, Any],
        serial: str | None = None,
    ) -> dict[str, Any]:
        """
        Set coffee parameters on an appliance.

        Args:
            params: Parameters to set
            serial: Appliance serial (auto-selects if only one appliance)

        Returns:
            API response
        """
        appliance = await self.get_appliance(serial)
        api = self._get_api_client()
        return await api.set_coffee_params(appliance.serial_number, params)

    # -------------------------------------------------------------------------
    # Configuration methods
    # -------------------------------------------------------------------------

    async def set_volume(self, volume: int, serial: str | None = None) -> dict[str, Any]:
        """Set the beep/sound volume (0-100)."""
        appliance = await self.get_appliance(serial)
        api = self._get_api_client()
        return await api.set_volume(appliance.serial_number, volume)

    async def set_brightness(self, brightness: int, serial: str | None = None) -> dict[str, Any]:
        """Set the display brightness (0-100)."""
        appliance = await self.get_appliance(serial)
        api = self._get_api_client()
        return await api.set_brightness(appliance.serial_number, brightness)

    async def set_color_theme(self, theme: str, serial: str | None = None) -> dict[str, Any]:
        """Set the display color theme (dark or light)."""
        appliance = await self.get_appliance(serial)
        api = self._get_api_client()
        return await api.set_color_theme(appliance.serial_number, theme)

    async def set_appliance_name(self, name: str, serial: str | None = None) -> dict[str, Any]:
        """Set the appliance name."""
        appliance = await self.get_appliance(serial)
        api = self._get_api_client()
        return await api.set_appliance_name(appliance.serial_number, name)

    async def set_work_light_brightness(self, brightness: int, serial: str | None = None) -> dict[str, Any]:
        """Set the work light (cup warmer) brightness (0-100)."""
        appliance = await self.get_appliance(serial)
        api = self._get_api_client()
        return await api.set_work_light_brightness(appliance.serial_number, brightness)

    async def set_wake_schedule(
        self,
        cron: str,
        enabled: bool = True,
        serial: str | None = None,
    ) -> dict[str, Any]:
        """Set wake schedule using cron format (e.g., "20 6 * * 1-5")."""
        appliance = await self.get_appliance(serial)
        api = self._get_api_client()
        return await api.set_wake_schedule(appliance.serial_number, cron, enabled)

    async def disable_wake_schedule(self, serial: str | None = None) -> dict[str, Any]:
        """Disable the wake schedule."""
        appliance = await self.get_appliance(serial)
        api = self._get_api_client()
        return await api.disable_wake_schedule(appliance.serial_number)

    # The methods below remain disabled until confirmed supported.
    #
    # async def set_grind_size(self, size: int, serial: str | None = None) -> dict[str, Any]:
    #     """Set the grind size (1-45)."""
    #     appliance = await self.get_appliance(serial)
    #     api = self._get_api_client()
    #     return await api.set_grind_size(appliance.serial_number, size)
    #
    # async def set_brew_temp(self, temp: float, serial: str | None = None) -> dict[str, Any]:
    #     """Set the brew boiler temperature in Celsius."""
    #     appliance = await self.get_appliance(serial)
    #     api = self._get_api_client()
    #     return await api.set_brew_temp(appliance.serial_number, temp)
    #
    # async def set_steam_temp(self, temp: float, serial: str | None = None) -> dict[str, Any]:
    #     """Set the steam boiler temperature in Celsius."""
    #     appliance = await self.get_appliance(serial)
    #     api = self._get_api_client()
    #     return await api.set_steam_temp(appliance.serial_number, temp)
    #
    # async def set_auto_off_time(self, minutes: int, serial: str | None = None) -> dict[str, Any]:
    #     """Set the auto-off idle time in minutes."""
    #     appliance = await self.get_appliance(serial)
    #     api = self._get_api_client()
    #     return await api.set_auto_off_time(appliance.serial_number, minutes)
    #
    # async def set_temp_unit(self, celsius: bool = True, serial: str | None = None) -> dict[str, Any]:
    #     """Set temperature unit (Celsius or Fahrenheit)."""
    #     appliance = await self.get_appliance(serial)
    #     api = self._get_api_client()
    #     return await api.set_temp_unit(appliance.serial_number, celsius)
    #
    # -------------------------------------------------------------------------

    # WebSocket methods

    async def connect_state_stream(
        self,
        serial: str | None = None,
        subscribe_all: bool = True,
    ) -> BrevilleWsClient:
        """
        Connect to the state stream WebSocket.

        Args:
            serial: Specific appliance serial to subscribe to
            subscribe_all: If True and no serial, subscribe to all appliances

        Returns:
            Connected BrevilleWsClient
        """
        ws = self._get_ws_client()
        await ws.connect()

        if serial:
            # Subscribe to specific appliance
            appliance = await self.get_appliance(serial)
            await ws.add_appliance(
                appliance.serial_number,
                app=self._app,
                model=appliance.model,
            )
        elif subscribe_all:
            # Subscribe to all appliances
            appliances = await self.list_appliances()
            for appliance in appliances:
                await ws.add_appliance(
                    appliance.serial_number,
                    app=self._app,
                    model=appliance.model,
                )

        return ws

    async def tail_state(
        self,
        serial: str | None = None,
        subscribe_all: bool = True,
    ) -> AsyncIterator[DeviceState]:
        """
        Stream state updates for appliances.

        Args:
            serial: Specific appliance serial to subscribe to
            subscribe_all: If True and no serial, subscribe to all appliances

        Yields:
            DeviceState objects as they arrive
        """
        ws = await self.connect_state_stream(serial, subscribe_all)
        async for state in ws.listen_states():
            yield state

    def get_last_state(self, serial: str | None = None) -> DeviceState | None:
        """
        Get the last known state for an appliance.

        Args:
            serial: Appliance serial number

        Returns:
            Last known DeviceState, or None
        """
        if self._ws_client:
            return self._ws_client.get_last_state(serial)
        return None

    # Context manager

    async def __aenter__(self) -> "SageCoffeeClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()
