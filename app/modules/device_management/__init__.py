"""
Device Management Module
Handles all device-related functionality including device registration, monitoring, and material management.
"""

from . import controllers
from .models import DeviceMaterialModel, DeviceModel
from .services import DeviceManagementService

__all__ = ["controllers", "DeviceManagementService", "DeviceModel", "DeviceMaterialModel"]
