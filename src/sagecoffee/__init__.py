"""Sage Coffee Control Library - Control Breville/Sage coffee machines via their cloud API."""

from importlib.metadata import PackageNotFoundError, version

from sagecoffee.client import SageCoffeeClient, TokenManager
from sagecoffee.models import Appliance, DeviceState, StateReport, TokenSet

try:
    __version__ = version("sagecoffee")
except PackageNotFoundError:
    __version__ = "0.0.0"
__all__ = [
    "Appliance",
    "DeviceState",
    "StateReport",
    "TokenSet",
    "SageCoffeeClient",
    "TokenManager",
]
