"""
Pydantic schemas for data validation and serialization.
Provides type-safe data models for API requests and responses.
"""

from .device_schemas import (
    DeviceCreateSchema,
    DeviceMaterialSchema,
    DeviceResponseSchema,
    DeviceUpdateSchema,
    MaterialRefillSchema,
)
from .material_schemas import (
    MaterialCatalogCreateSchema,
    MaterialCatalogResponseSchema,
    MaterialCatalogUpdateSchema,
)

__all__ = [
    # Device schemas
    "DeviceCreateSchema",
    "DeviceUpdateSchema",
    "DeviceResponseSchema",
    "DeviceMaterialSchema",
    "MaterialRefillSchema",
    # Material schemas
    "MaterialCatalogCreateSchema",
    "MaterialCatalogUpdateSchema",
    "MaterialCatalogResponseSchema",
]
