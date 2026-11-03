"""Data models for the Sage Coffee library."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(UTC)


class TokenSet(BaseModel):
    """OAuth token set from Breville Auth0."""

    access_token: str | None = None
    id_token: str | None = None
    refresh_token: str | None = None
    expires_in: int = 86400
    token_type: str = "Bearer"
    scope: str | None = None
    obtained_at: datetime = Field(default_factory=_utcnow)

    def is_expired(self, skew_seconds: int = 60) -> bool:
        """Check if the token is expired or will expire within skew_seconds."""
        if not self.id_token and not self.access_token:
            return True

        # Try to get expiry from JWT if available
        from sagecoffee.auth import decode_jwt_without_verify

        token = self.id_token or self.access_token
        if token:
            try:
                payload = decode_jwt_without_verify(token)
                exp = payload.get("exp")
                if exp:
                    expiry_time = datetime.fromtimestamp(exp, tz=UTC)
                    return _utcnow() >= expiry_time - timedelta(seconds=skew_seconds)
            except Exception:
                pass

        # Fallback to obtained_at + expires_in
        # Make obtained_at timezone-aware if it isn't
        obtained = self.obtained_at
        if obtained.tzinfo is None:
            obtained = obtained.replace(tzinfo=UTC)

        expiry_time = obtained + timedelta(seconds=self.expires_in)
        return _utcnow() >= expiry_time - timedelta(seconds=skew_seconds)

    def auth0_sub(self) -> str | None:
        """Extract the Auth0 subject (user ID) from the id_token."""
        if not self.id_token:
            return None

        from sagecoffee.auth import decode_jwt_without_verify

        try:
            payload = decode_jwt_without_verify(self.id_token)
            return payload.get("sub")
        except Exception:
            return None


class Appliance(BaseModel):
    """A Breville/Sage appliance."""

    model_config = ConfigDict(populate_by_name=True)

    serial_number: str = Field(alias="serialNumber")
    model: str
    name: str | None = None
    pairing_type: str | None = Field(default=None, alias="pairingType")


class StateReport(BaseModel):
    """WebSocket state report message from an appliance."""

    model_config = ConfigDict(populate_by_name=True)

    serial_number: str = Field(alias="serialNumber")
    message_type: Literal["stateReport"] = Field(alias="messageType")
    data: dict[str, Any]
    version: int | None = None


BOILER_ROLE_BREW = "brew"
BOILER_ROLE_STEAM = "steam"


class BoilerState(BaseModel):
    """State of a boiler."""

    id: str
    current_temp: float | None = None
    target_temp: float | None = None
    role: str | None = None


class DeviceState(BaseModel):
    """Parsed device state from a StateReport."""

    raw_data: dict[str, Any]
    serial_number: str
    version: int | None = None

    @property
    def reported(self) -> dict[str, Any]:
        """Get the reported state."""
        return self.raw_data.get("reported", {})

    @property
    def desired(self) -> dict[str, Any]:
        """Get the desired state."""
        return self.raw_data.get("desired", {})

    @property
    def reported_state(self) -> str | None:
        """Get the reported machine state (e.g., 'asleep', 'warming', 'ready')."""
        return self.reported.get("state")

    @property
    def desired_state(self) -> str | None:
        """Get the desired machine state."""
        return self.desired.get("state")

    @property
    def cfg_default(self) -> dict[str, Any]:
        """Get the default config block (reported as nested or dotted key)."""
        cfg = self.reported.get("cfg", {})
        nested = cfg.get("default") if isinstance(cfg, dict) else None
        if isinstance(nested, dict) and nested:
            return nested
        cfg_default = self.reported.get("cfg.default", {})
        return cfg_default if isinstance(cfg_default, dict) else {}

    @property
    def boiler_temps(self) -> list[BoilerState]:
        """
        Get boiler temperatures.

        Dual boiler machines report the steam boiler at index 0 and the brew
        boiler at index 1. Single boiler machines report only a brew boiler,
        at index 0.
        """
        boiler_data = self.reported.get("boiler", [])
        if not isinstance(boiler_data, list):
            return []
        entries = [(i, b) for i, b in enumerate(boiler_data) if isinstance(b, dict)]
        if len(boiler_data) == 1:
            roles = {0: BOILER_ROLE_BREW}
        else:
            roles = {0: BOILER_ROLE_STEAM, 1: BOILER_ROLE_BREW}
        return [
            BoilerState(
                id=str(i),
                current_temp=boiler.get("cur_temp"),
                target_temp=boiler.get("temp_sp"),
                role=roles.get(i),
            )
            for i, boiler in entries
        ]

    @property
    def is_single_boiler(self) -> bool:
        """Check if the machine reports exactly one boiler."""
        boiler_data = self.reported.get("boiler")
        return isinstance(boiler_data, list) and len(boiler_data) == 1

    @property
    def brew_boiler(self) -> BoilerState | None:
        """Get the brew boiler, if reported."""
        return next((b for b in self.boiler_temps if b.role == BOILER_ROLE_BREW), None)

    @property
    def steam_boiler(self) -> BoilerState | None:
        """Get the steam boiler (dual boiler machines only)."""
        return next((b for b in self.boiler_temps if b.role == BOILER_ROLE_STEAM), None)

    @property
    def wake_schedule(self) -> list[dict[str, Any]]:
        """Get the wake schedules, e.g. [{"cron": "20 6 * * 1-5", "on": True}]."""
        schedule = self.cfg_default.get("wake_schedule")
        if not isinstance(schedule, list):
            return []
        return [dict(s) for s in schedule if isinstance(s, dict)]

    @property
    def errors(self) -> list[str]:
        """Get the reported appliance error names (e.g. "WaterTankEmpty")."""
        errors = self.reported.get("errors")
        if not isinstance(errors, list):
            return []
        return [str(e) for e in errors]

    @property
    def signal_strength(self) -> int | float | None:
        """Get the reported Wi-Fi signal strength."""
        return self.reported.get("signal_strength")

    @property
    def firmware(self) -> dict[str, Any]:
        """Get the reported firmware versions."""
        firmware = self.reported.get("firmware")
        return firmware if isinstance(firmware, dict) else {}

    @property
    def grind_size(self) -> int | None:
        """Get the grind size setting."""
        return self.reported.get("grind.size_setting") or self.reported.get("grind", {}).get(
            "size_setting"
        )

    @property
    def is_remote_wake_enabled(self) -> bool:
        """Check if remote wake is enabled."""
        return bool(self.cfg_default.get("remote_wake_enable"))

    @property
    def timezone(self) -> str | None:
        """Get the configured timezone."""
        return self.cfg_default.get("timezone")

    @classmethod
    def from_state_report(cls, report: StateReport) -> "DeviceState":
        """Create a DeviceState from a StateReport."""
        return cls(
            raw_data=report.data,
            serial_number=report.serial_number,
            version=report.version,
        )


class WsMessage(BaseModel):
    """Base class for WebSocket messages."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    action: str | None = None
    message_type: str | None = Field(default=None, alias="messageType")


class AddApplianceMessage(BaseModel):
    """Message to register an appliance on the WebSocket connection."""

    model_config = ConfigDict(populate_by_name=True)

    action: Literal["addAppliance"] = "addAppliance"
    serial_number: str = Field(alias="serialNumber")
    app: str = "sageCoffee"
    model: str = "BES995"


class PingMessage(BaseModel):
    """Ping message for WebSocket keepalive."""

    action: Literal["ping"] = "ping"


class PongMessage(BaseModel):
    """Pong response from WebSocket server."""

    model_config = ConfigDict(populate_by_name=True)

    message_type: Literal["pong"] = Field(alias="messageType")
