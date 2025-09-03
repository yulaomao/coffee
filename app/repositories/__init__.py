"""
Repository pattern implementation for data access abstraction.
Provides a uniform interface for data operations across different entities.
"""

from .base_repository import BaseRepository
from .device_repository import DeviceRepository
from .material_repository import DeviceMaterialRepository, MaterialRepository
from .order_repository import OrderRepository
from .user_repository import UserRepository

__all__ = [
    "BaseRepository",
    "DeviceRepository",
    "MaterialRepository",
    "DeviceMaterialRepository",
    "OrderRepository",
    "UserRepository",
]
