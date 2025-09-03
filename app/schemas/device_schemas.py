"""
Pydantic schemas for device-related operations.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class DeviceCreateSchema(BaseModel):
    """Schema for creating a new device."""

    device_no: str = Field(..., min_length=1, max_length=50, description="Unique device number")
    name: Optional[str] = Field(None, max_length=100, description="Device display name")
    location: Optional[str] = Field(None, max_length=200, description="Device location")
    merchant_id: int = Field(..., gt=0, description="Merchant ID")
    status: Optional[str] = Field("offline", description="Initial device status")

    @validator("device_no")
    def validate_device_no(cls, v):
        if not v.strip():
            raise ValueError("Device number cannot be empty")
        return v.strip()

    @validator("status")
    def validate_status(cls, v):
        valid_statuses = ["online", "offline", "fault", "maintenance"]
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of: {valid_statuses}")
        return v


class DeviceUpdateSchema(BaseModel):
    """Schema for updating device information."""

    name: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=200)
    status: Optional[str] = Field(None)
    callback_url: Optional[str] = Field(None, max_length=500)

    @validator("status")
    def validate_status(cls, v):
        if v is not None:
            valid_statuses = ["online", "offline", "fault", "maintenance"]
            if v not in valid_statuses:
                raise ValueError(f"Status must be one of: {valid_statuses}")
        return v


class DeviceMaterialSchema(BaseModel):
    """Schema for device material configuration."""

    material_id: int = Field(..., gt=0)
    capacity: float = Field(..., gt=0, description="Maximum capacity")
    threshold: float = Field(..., gt=0, description="Alert threshold")
    remain: Optional[float] = Field(0.0, ge=0, description="Current remaining amount")

    @validator("threshold")
    def validate_threshold(cls, v, values):
        if "capacity" in values and v > values["capacity"]:
            raise ValueError("Threshold cannot be greater than capacity")
        return v

    @validator("remain")
    def validate_remain(cls, v, values):
        if "capacity" in values and v > values["capacity"]:
            raise ValueError("Remaining amount cannot exceed capacity")
        return v


class MaterialRefillSchema(BaseModel):
    """Schema for material refill operations."""

    material_id: int = Field(..., gt=0)
    amount: Optional[float] = Field(
        None, gt=0, description="Amount to add (None = fill to capacity)"
    )


class DeviceStatusUpdateSchema(BaseModel):
    """Schema for device status updates."""

    status: str = Field(...)
    details: Optional[Dict[str, Any]] = Field(None, description="Additional status details")

    @validator("status")
    def validate_status(cls, v):
        valid_statuses = ["online", "offline", "fault", "maintenance"]
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of: {valid_statuses}")
        return v


class DeviceResponseSchema(BaseModel):
    """Schema for device API responses."""

    id: int
    device_no: str
    name: Optional[str]
    location: Optional[str]
    status: str
    merchant_id: int
    callback_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    # Optional aggregated data
    material_count: Optional[int] = None
    low_material_count: Optional[int] = None
    last_order_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DeviceMaterialResponseSchema(BaseModel):
    """Schema for device material responses."""

    bin_id: int
    name: str
    material_name: Optional[str]
    unit: str
    remain: float
    capacity: float
    threshold: float
    stock_percent: float
    alert_level: str  # 'normal', 'warning', 'critical'
    updated_at: datetime

    class Config:
        from_attributes = True
