"""
Pydantic schemas for material-related operations.
"""

from typing import Optional

from pydantic import BaseModel, Field, validator


class MaterialCatalogCreateSchema(BaseModel):
    """Schema for creating a new material."""

    code: Optional[str] = Field(
        None, min_length=1, max_length=20, description="Unique material code"
    )
    name: str = Field(..., min_length=1, max_length=100, description="Material name")
    category: Optional[str] = Field(None, max_length=50, description="Material category")
    unit: str = Field(..., min_length=1, max_length=10, description="Unit of measurement")
    default_capacity: Optional[float] = Field(
        None, gt=0, description="Default capacity for devices"
    )
    description: Optional[str] = Field(None, max_length=500, description="Material description")

    @validator("code")
    def validate_code(cls, v):
        if v and not v.strip():
            raise ValueError("Material code cannot be empty")
        return v.strip() if v else v

    @validator("name")
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError("Material name cannot be empty")
        return v.strip()

    @validator("unit")
    def validate_unit(cls, v):
        if not v.strip():
            raise ValueError("Unit cannot be empty")
        return v.strip()


class MaterialCatalogUpdateSchema(BaseModel):
    """Schema for updating material information."""

    code: Optional[str] = Field(None, min_length=1, max_length=20)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    category: Optional[str] = Field(None, max_length=50)
    unit: Optional[str] = Field(None, min_length=1, max_length=10)
    default_capacity: Optional[float] = Field(None, gt=0)
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = Field(None, description="Material active status")

    @validator("code")
    def validate_code(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Material code cannot be empty")
        return v.strip() if v else v

    @validator("name")
    def validate_name(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Material name cannot be empty")
        return v.strip() if v else v


class MaterialCatalogResponseSchema(BaseModel):
    """Schema for material API responses."""

    id: int
    code: Optional[str]
    name: str
    category: Optional[str]
    unit: str
    default_capacity: Optional[float]
    description: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str

    # Optional aggregated data
    usage_count: Optional[int] = None
    total_stock: Optional[float] = None
    devices_using: Optional[int] = None

    class Config:
        from_attributes = True
