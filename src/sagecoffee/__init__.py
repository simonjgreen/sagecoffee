"""Sage Coffee Control Library - Control Breville/Sage coffee machines via their cloud API."""

from importlib.metadata import PackageNotFoundError, version

from sagecoffee.auth import MfaRequiredError
from sagecoffee.client import SageCoffeeClient, TokenManager
from sagecoffee.http_api import APP_BREVILLE, APP_LELIT, APP_SAGE, APPS, DEFAULT_APP
from sagecoffee.models import Appliance, BoilerState, DeviceState, StateReport, TokenSet

try:
    __version__ = version("sagecoffee")
except PackageNotFoundError:
    __version__ = "0.0.0"
__all__ = [
    "APP_BREVILLE",
    "APP_LELIT",
    "APP_SAGE",
    "APPS",
    "DEFAULT_APP",
    "Appliance",
    "BoilerState",
    "DeviceState",
    "MfaRequiredError",
    "StateReport",
    "TokenSet",
    "SageCoffeeClient",
    "TokenManager",
]
