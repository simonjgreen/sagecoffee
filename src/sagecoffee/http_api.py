"""REST API client for Breville/Sage appliances."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import httpx

from sagecoffee.logging import get_logger, redact_dict
from sagecoffee.models import Appliance

logger = get_logger("http_api")

# API base URLs
API_BASE_URL = "https://iot-api.breville.com"
APPLIANCE_API_BASE = f"{API_BASE_URL}/appliance/v1"
USER_API_BASE = f"{API_BASE_URL}/user/v2"

# Default app identifier
DEFAULT_APP = "sageCoffee"


class BrevilleApiClient:
    """
    REST API client for Breville/Sage appliances.

    Handles authentication headers, retry logic, and token refresh.
    """

    def __init__(
        self,
        get_id_token: Callable[[], Awaitable[str]],
        refresh_token_callback: Callable[[], Awaitable[None]] | None = None,
        app: str = DEFAULT_APP,
        http_client: httpx.AsyncClient | None = None,
    ):
        """
        Initialize the API client.

        Args:
            get_id_token: Async callable that returns the current id_token
            refresh_token_callback: Async callable to refresh tokens on 401
            app: App identifier for requests
            http_client: Optional httpx client (for testing)
        """
        self._get_id_token = get_id_token
        self._refresh_callback = refresh_token_callback
        self._app = app
        self._http_client = http_client
        self._owns_client = http_client is None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client if we own it."""
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _get_headers(self) -> dict[str, str]:
        """Get the required headers for API requests."""
        id_token = await self._get_id_token()
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "app": self._app,
            "sf-id-token": id_token,
        }

    async def request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        retry_on_401: bool = True,
    ) -> dict[str, Any]:
        """
        Make an API request.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (will be appended to base URL)
            json: JSON body for the request
            params: Query parameters
            retry_on_401: Whether to retry with refreshed token on 401

        Returns:
            Response JSON as dictionary

        Raises:
            httpx.HTTPStatusError: If request fails after retries
        """
        client = await self._get_client()
        headers = await self._get_headers()

        # Build full URL
        if path.startswith("http"):
            url = path
        elif path.startswith("/"):
            url = f"{API_BASE_URL}{path}"
        else:
            url = f"{API_BASE_URL}/{path}"

        logger.debug(
            "API request: %s %s",
            method,
            url,
        )
        if json:
            logger.debug("Request body: %s", redact_dict(json))

        try:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                params=params,
            )

            # Handle 401 with retry
            if response.status_code == 401 and retry_on_401 and self._refresh_callback:
                logger.info("Got 401, refreshing token and retrying")
                await self._refresh_callback()
                headers = await self._get_headers()
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json,
                    params=params,
                )

            # Handle 429 with backoff
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "5"))
                logger.warning("Rate limited, waiting %d seconds", retry_after)
                await asyncio.sleep(retry_after)
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json,
                    params=params,
                )

            response.raise_for_status()

            # Handle empty responses
            if response.status_code == 204 or not response.content:
                return {}

            return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                "API error: %s %s -> %d",
                method,
                url,
                e.response.status_code,
            )
            raise

    async def raw_post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        """
        Make a raw POST request.

        Args:
            path: API path
            json: JSON body

        Returns:
            Response JSON
        """
        return await self.request("POST", path, json=json)

    async def raw_get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """
        Make a raw GET request.

        Args:
            path: API path
            params: Query parameters

        Returns:
            Response JSON
        """
        return await self.request("GET", path, params=params)

    # Appliance endpoints

    async def set_coffee_params(
        self,
        serial: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Set coffee parameters on an appliance.

        Args:
            serial: Appliance serial number
            payload: Parameters to set (e.g., {"state": "ready"})

        Returns:
            Response JSON
        """
        path = f"{APPLIANCE_API_BASE}/appliances/{serial}/set-coffeeParams"
        return await self.request("POST", path, json=payload)

    async def wake(self, serial: str) -> dict[str, Any]:
        """
        Wake up an appliance.

        Args:
            serial: Appliance serial number

        Returns:
            Response JSON
        """
        logger.info("Waking appliance %s", serial)
        return await self.set_coffee_params(serial, {"state": "ready"})

    async def sleep(self, serial: str) -> dict[str, Any]:
        """
        Put an appliance to sleep.

        Args:
            serial: Appliance serial number

        Returns:
            Response JSON
        """
        logger.info("Putting appliance %s to sleep", serial)
        return await self.set_coffee_params(serial, {"state": "asleep"})

    # -------------------------------------------------------------------------
    # Configuration endpoints - COMMENTED OUT
    # These methods accept the API calls but don't actually change machine
    # settings. Held here for potential future functionality.
    # -------------------------------------------------------------------------
    #
    # async def set_grind_size(self, serial: str, size: int) -> dict[str, Any]:
    #     """Set the grind size (1-45)."""
    #     logger.info("Setting grind size to %d for %s", size, serial)
    #     return await self.set_coffee_params(serial, {"cfg": {"grind": {"size_setting": size}}})
    #
    # async def set_brew_temp(self, serial: str, temp: float) -> dict[str, Any]:
    #     """Set the brew boiler temperature in Celsius."""
    #     logger.info("Setting brew temp to %.1f for %s", temp, serial)
    #     return await self.set_coffee_params(serial, {"cfg": {"boiler": {"temp_sp": temp}}})
    #
    # async def set_steam_temp(self, serial: str, temp: float) -> dict[str, Any]:
    #     """Set the steam boiler temperature in Celsius."""
    #     logger.info("Setting steam temp to %.1f for %s", temp, serial)
    #     return await self.set_coffee_params(serial, {"cfg": {"default": {"steam_temp": temp}}})
    #
    # async def set_volume(self, serial: str, volume: int) -> dict[str, Any]:
    #     """Set the beep/sound volume (0-100)."""
    #     logger.info("Setting volume to %d for %s", volume, serial)
    #     return await self.set_coffee_params(serial, {"cfg": {"default": {"vol": volume}}})
    #
    # async def set_brightness(self, serial: str, brightness: int) -> dict[str, Any]:
    #     """Set the display brightness (0-100)."""
    #     logger.info("Setting brightness to %d for %s", brightness, serial)
    #     return await self.set_coffee_params(serial, {"cfg": {"default": {"brightness": brightness}}})
    #
    # async def set_work_light_brightness(self, serial: str, brightness: int) -> dict[str, Any]:
    #     """Set the work light (cup warmer) brightness (0-100)."""
    #     logger.info("Setting work light brightness to %d for %s", brightness, serial)
    #     return await self.set_coffee_params(serial, {"cfg": {"default": {"work_light_brightness": brightness}}})
    #
    # async def set_auto_off_time(self, serial: str, minutes: int) -> dict[str, Any]:
    #     """Set the auto-off idle time in minutes."""
    #     logger.info("Setting auto-off time to %d minutes for %s", minutes, serial)
    #     return await self.set_coffee_params(serial, {"cfg": {"default": {"idle_time": minutes}}})
    #
    # async def set_temp_unit(self, serial: str, celsius: bool = True) -> dict[str, Any]:
    #     """Set temperature unit (0=Celsius, 1=Fahrenheit)."""
    #     unit = 0 if celsius else 1
    #     logger.info("Setting temp unit to %s for %s", "Celsius" if celsius else "Fahrenheit", serial)
    #     return await self.set_coffee_params(serial, {"cfg": {"default": {"temp_unit": unit}}})
    #
    # async def set_wake_schedule(self, serial: str, cron: str, enabled: bool = True) -> dict[str, Any]:
    #     """Set wake schedule using cron format (e.g., "20 6 * * 1-5" for 6:20 AM weekdays)."""
    #     logger.info("Setting wake schedule to '%s' (enabled=%s) for %s", cron, enabled, serial)
    #     schedule = [{"cron": cron, "on": enabled}]
    #     return await self.set_coffee_params(serial, {"cfg": {"default": {"wake_schedule": schedule}}})
    #
    # async def disable_wake_schedule(self, serial: str) -> dict[str, Any]:
    #     """Disable the wake schedule."""
    #     logger.info("Disabling wake schedule for %s", serial)
    #     return await self.set_coffee_params(serial, {"cfg": {"default": {"wake_schedule": []}}})
    #
    # -------------------------------------------------------------------------

    # User/discovery endpoints

    async def list_appliances(self, auth0_sub: str) -> list[Appliance]:
        """
        List appliances for a user.

        Args:
            auth0_sub: Auth0 subject (user ID) from id_token

        Returns:
            List of Appliance objects
        """
        # URL-encode the sub (auth0|... -> auth0%7C...)
        encoded_sub = quote(auth0_sub, safe="")
        path = f"{USER_API_BASE}/user/{encoded_sub}/appliances"

        logger.debug("Listing appliances for user")
        response = await self.request("GET", path)

        appliances = []
        for item in response.get("appliances", []):
            try:
                appliances.append(Appliance.model_validate(item))
            except Exception as e:
                logger.warning("Failed to parse appliance: %s", e)

        logger.info("Found %d appliances", len(appliances))
        return appliances


class SyncBrevilleApiClient:
    """Synchronous wrapper for BrevilleApiClient."""

    def __init__(
        self,
        id_token: str,
        app: str = DEFAULT_APP,
    ):
        """
        Initialize the sync API client.

        Args:
            id_token: The id_token for authentication
            app: App identifier for requests
        """
        self._id_token = id_token
        self._app = app

    def _get_headers(self) -> dict[str, str]:
        """Get the required headers for API requests."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "app": self._app,
            "sf-id-token": self._id_token,
        }

    def request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Make a synchronous API request."""
        headers = self._get_headers()

        if path.startswith("http"):
            url = path
        elif path.startswith("/"):
            url = f"{API_BASE_URL}{path}"
        else:
            url = f"{API_BASE_URL}/{path}"

        with httpx.Client(timeout=30.0) as client:
            response = client.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                params=params,
            )
            response.raise_for_status()

            if response.status_code == 204 or not response.content:
                return {}

            return response.json()

    def set_coffee_params(self, serial: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Set coffee parameters (sync version)."""
        path = f"{APPLIANCE_API_BASE}/appliances/{serial}/set-coffeeParams"
        return self.request("POST", path, json=payload)

    def wake(self, serial: str) -> dict[str, Any]:
        """Wake up an appliance (sync version)."""
        return self.set_coffee_params(serial, {"state": "ready"})

    def sleep(self, serial: str) -> dict[str, Any]:
        """Put an appliance to sleep (sync version)."""
        return self.set_coffee_params(serial, {"state": "asleep"})

    def list_appliances(self, auth0_sub: str) -> list[Appliance]:
        """List appliances for a user (sync version)."""
        encoded_sub = quote(auth0_sub, safe="")
        path = f"{USER_API_BASE}/user/{encoded_sub}/appliances"
        response = self.request("GET", path)

        appliances = []
        for item in response.get("appliances", []):
            try:
                appliances.append(Appliance.model_validate(item))
            except Exception:
                pass

        return appliances
