"""Configuration storage for Sage Coffee library."""

import os
import stat
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from sagecoffee.models import TokenSet

# Default config path
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "sagecoffee"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.toml"

# Environment variable names
ENV_PREFIX = "SAGECOFFEE_"
ENV_CLIENT_ID = f"{ENV_PREFIX}CLIENT_ID"
ENV_USERNAME = f"{ENV_PREFIX}USERNAME"
ENV_PASSWORD = f"{ENV_PREFIX}PASSWORD"
ENV_REFRESH_TOKEN = f"{ENV_PREFIX}REFRESH_TOKEN"
ENV_SERIAL = f"{ENV_PREFIX}SERIAL"
ENV_MODEL = f"{ENV_PREFIX}MODEL"
ENV_APP = f"{ENV_PREFIX}APP"
ENV_ID_TOKEN = f"{ENV_PREFIX}ID_TOKEN"
ENV_ACCESS_TOKEN = f"{ENV_PREFIX}ACCESS_TOKEN"

# Defaults
DEFAULT_CLIENT_ID = "gSo1NuhsGPs5J2e5zyw0oGaSqdqsq2vc"
DEFAULT_MODEL = "BES995"
DEFAULT_APP = "sageCoffee"


class ConfigStore:
    """
    Configuration storage with priority: CLI flags > env vars > config file > defaults.

    Handles secure storage of refresh tokens with proper file permissions.
    """

    def __init__(self, config_path: Path | None = None):
        """
        Initialize the config store.

        Args:
            config_path: Path to config file (default: ~/.config/sagecoffee/config.toml)
        """
        self.config_path = config_path or DEFAULT_CONFIG_FILE
        self._config: dict[str, Any] = {}
        self._loaded = False

    def _ensure_dir(self) -> None:
        """Ensure the config directory exists with proper permissions."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        # Set directory permissions to 0700 (owner only)
        os.chmod(self.config_path.parent, stat.S_IRWXU)

    def _check_permissions(self) -> bool:
        """
        Check if config file has secure permissions.

        Returns:
            True if permissions are secure (0600), False otherwise
        """
        if not self.config_path.exists():
            return True

        mode = self.config_path.stat().st_mode
        # Check if group or others have any permissions
        return not mode & (stat.S_IRWXG | stat.S_IRWXO)

    def _warn_permissions(self) -> None:
        """Print a warning if config file permissions are too permissive."""
        if not self._check_permissions():
            import warnings

            warnings.warn(
                f"Config file {self.config_path} has overly permissive permissions. "
                f"Consider running: chmod 600 {self.config_path}",
                UserWarning,
                stacklevel=3,
            )

    def load(self) -> dict[str, Any]:
        """
        Load configuration from file.

        Returns:
            Configuration dictionary
        """
        if self._loaded:
            return self._config

        if self.config_path.exists():
            self._warn_permissions()
            with open(self.config_path, "rb") as f:
                self._config = tomllib.load(f)
        else:
            self._config = {}

        self._loaded = True
        return self._config

    def save(self, config: dict[str, Any] | None = None) -> None:
        """
        Save configuration to file with secure permissions.

        Args:
            config: Configuration to save (uses internal config if None)
        """
        if config is not None:
            self._config = config

        self._ensure_dir()

        # Write to temp file first, then rename (atomic)
        temp_path = self.config_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            tomli_w.dump(self._config, f)

        # Set secure permissions before rename
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600

        # Atomic rename
        temp_path.rename(self.config_path)

    def get(self, key: str, default: Any = None, cli_value: Any = None) -> Any:
        """
        Get a configuration value with priority: CLI > env > config > default.

        Args:
            key: Configuration key (e.g., 'client_id')
            default: Default value if not found
            cli_value: Value from CLI flag (highest priority)

        Returns:
            Configuration value
        """
        # Priority 1: CLI flag
        if cli_value is not None:
            return cli_value

        # Priority 2: Environment variable
        env_key = f"{ENV_PREFIX}{key.upper()}"
        env_value = os.environ.get(env_key)
        if env_value is not None:
            return env_value

        # Priority 3: Config file
        self.load()
        if key in self._config:
            return self._config[key]

        # Priority 4: Default
        return default

    def set(self, key: str, value: Any) -> None:
        """
        Set a configuration value and save.

        Args:
            key: Configuration key
            value: Value to set
        """
        self.load()
        self._config[key] = value
        self.save()

    def delete(self, key: str) -> None:
        """
        Delete a configuration value and save.

        Args:
            key: Configuration key to delete
        """
        self.load()
        if key in self._config:
            del self._config[key]
            self.save()

    # Convenience properties for common config values

    @property
    def client_id(self) -> str:
        """Get the OAuth client ID."""
        return self.get("client_id", DEFAULT_CLIENT_ID)

    @client_id.setter
    def client_id(self, value: str) -> None:
        """Set the OAuth client ID."""
        self.set("client_id", value)

    @property
    def refresh_token(self) -> str | None:
        """Get the refresh token."""
        return self.get("refresh_token")

    @refresh_token.setter
    def refresh_token(self, value: str) -> None:
        """Set the refresh token."""
        self.set("refresh_token", value)

    @property
    def serial(self) -> str | None:
        """Get the appliance serial number."""
        return self.get("serial")

    @serial.setter
    def serial(self, value: str) -> None:
        """Set the appliance serial number."""
        self.set("serial", value)

    @property
    def model(self) -> str:
        """Get the appliance model."""
        return self.get("model", DEFAULT_MODEL)

    @model.setter
    def model(self, value: str) -> None:
        """Set the appliance model."""
        self.set("model", value)

    @property
    def app(self) -> str:
        """Get the app identifier."""
        return self.get("app", DEFAULT_APP)

    @app.setter
    def app(self, value: str) -> None:
        """Set the app identifier."""
        self.set("app", value)

    def get_token_set(self) -> TokenSet | None:
        """
        Get a TokenSet from environment variables or config.

        This is useful for restoring tokens from storage.
        Note: This only restores refresh_token, id_token, and access_token
        if they are explicitly stored/provided.

        Returns:
            TokenSet if refresh_token is available, None otherwise
        """
        refresh_token = self.get("refresh_token")
        if not refresh_token:
            return None

        return TokenSet(
            refresh_token=refresh_token,
            id_token=self.get("id_token"),
            access_token=self.get("access_token"),
        )

    def save_token_set(self, tokens: TokenSet) -> None:
        """
        Save a TokenSet to config.

        Only saves refresh_token by default (not id_token or access_token
        since those are short-lived).

        Args:
            tokens: TokenSet to save
        """
        if tokens.refresh_token:
            self.set("refresh_token", tokens.refresh_token)

    def is_configured(self) -> bool:
        """
        Check if minimum configuration is present.

        Returns:
            True if refresh_token is available (client_id has a default)
        """
        return bool(self.refresh_token)

    def get_all(self) -> dict[str, Any]:
        """
        Get all configuration values (for debugging, with redaction).

        Returns:
            Dictionary of all config values
        """
        self.load()
        return {
            "client_id": self.client_id,
            "refresh_token": "[REDACTED]" if self.refresh_token else None,
            "serial": self.serial,
            "model": self.model,
            "app": self.app,
            "config_path": str(self.config_path),
            "is_configured": self.is_configured(),
        }
