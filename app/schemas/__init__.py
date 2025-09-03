"""
Pydantic schemas for data validation and serialization.
Provides type-safe data models for API requests and responses.
"""
from .device_schemas import (
    DeviceCreateSchema,
    DeviceUpdateSchema,
    DeviceResponseSchema,
    DeviceMaterialSchema,
    MaterialRefillSchema
)
from .material_schemas import (
    MaterialCatalogCreateSchema,
    MaterialCatalogUpdateSchema,
    MaterialCatalogResponseSchema
)
from .order_schemas import (
    OrderCreateSchema,
    OrderResponseSchema,
    OrderStatisticsSchema
)
from .user_schemas import (
    UserCreateSchema,
    UserUpdateSchema,
    UserResponseSchema,
    AuthenticationSchema
)

__all__ = [
    # Device schemas
    'DeviceCreateSchema',
    'DeviceUpdateSchema',
    'DeviceResponseSchema',
    'DeviceMaterialSchema',
    'MaterialRefillSchema',
    
    # Material schemas
    'MaterialCatalogCreateSchema',
    'MaterialCatalogUpdateSchema',
    'MaterialCatalogResponseSchema',
    
    # Order schemas
    'OrderCreateSchema',
    'OrderResponseSchema',
    'OrderStatisticsSchema',
    
    # User schemas
    'UserCreateSchema',
    'UserUpdateSchema', 
    'UserResponseSchema',
    'AuthenticationSchema'
]