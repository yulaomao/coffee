"""
Device Management Domain Models
Domain-specific models and business rules for device management.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from ...models import Device
from ...models import DeviceMaterial as DeviceMaterialEntity


class DeviceModel(BaseModel):
    """Device domain model with business rules."""

    device_no: str
    merchant_id: int
    status: str
    address_detail: Optional[str] = None
    model: Optional[str] = None
    firmware_version: Optional[str] = None
    last_seen: Optional[datetime] = None

    # Business properties
    is_online: bool = False
    health_score: Optional[int] = None
    material_alert_count: int = 0

    @validator("status")
    def validate_status(cls, v):
        valid_statuses = ["online", "offline", "fault", "maintenance"]
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of: {valid_statuses}")
        return v

    @property
    def is_healthy(self) -> bool:
        """Check if device is in healthy state."""
        return (
            self.status in ["online"]
            and self.material_alert_count == 0
            and (self.health_score is None or self.health_score >= 80)
        )

    @property
    def requires_maintenance(self) -> bool:
        """Check if device requires maintenance."""
        return (
            self.status == "fault"
            or self.material_alert_count > 0
            or (self.health_score is not None and self.health_score < 60)
        )

    def can_process_order(self) -> tuple[bool, Optional[str]]:
        """Check if device can process orders."""
        if self.status != "online":
            return False, f"Device is {self.status}"

        if self.material_alert_count > 0:
            return False, "Critical material shortage"

        return True, None


class DeviceMaterialModel(BaseModel):
    """Device material domain model with business rules."""

    device_id: int
    material_id: int
    material_name: str
    unit: str
    remain: float
    capacity: float
    threshold: float

    @validator("remain")
    def validate_remain(cls, v, values):
        if "capacity" in values and v > values["capacity"]:
            raise ValueError("Remaining amount cannot exceed capacity")
        return v

    @validator("threshold")
    def validate_threshold(cls, v, values):
        if "capacity" in values and v > values["capacity"]:
            raise ValueError("Threshold cannot exceed capacity")
        return v

    @property
    def stock_percentage(self) -> float:
        """Calculate stock percentage."""
        return round((self.remain / self.capacity) * 100, 2)

    @property
    def threshold_percentage(self) -> float:
        """Calculate threshold percentage."""
        return round((self.remain / self.threshold) * 100, 2)

    @property
    def alert_level(self) -> str:
        """Get material alert level."""
        if self.remain <= self.threshold:
            return "critical"
        elif self.remain <= self.threshold * 1.2:
            return "warning"
        elif self.remain <= self.threshold * 1.5:
            return "info"
        else:
            return "normal"

    @property
    def is_critical(self) -> bool:
        """Check if material is at critical level."""
        return self.alert_level == "critical"

    @property
    def days_remaining(self) -> Optional[int]:
        """Estimate days remaining based on current usage (simplified)."""
        # This is a simplified calculation - in real implementation,
        # you would use historical consumption data
        if self.remain <= 0:
            return 0

        # Assume average daily consumption is 10% of capacity
        daily_consumption = self.capacity * 0.1
        if daily_consumption <= 0:
            return None

        return int(self.remain / daily_consumption)

    def can_refill(self, amount: float) -> tuple[bool, Optional[str]]:
        """Check if material can be refilled with given amount."""
        if amount <= 0:
            return False, "Refill amount must be positive"

        if self.remain + amount > self.capacity:
            return False, f"Refill would exceed capacity ({self.capacity})"

        return True, None

    def calculate_refill_to_capacity(self) -> float:
        """Calculate amount needed to fill to capacity."""
        return max(0, self.capacity - self.remain)

    def calculate_refill_to_safe_level(self, safe_multiplier: float = 0.8) -> float:
        """Calculate amount needed to fill to safe level."""
        safe_level = self.capacity * safe_multiplier
        return max(0, safe_level - self.remain)


class DeviceMaintenanceModel(BaseModel):
    """Device maintenance domain model."""

    device_id: int
    maintenance_type: str  # 'scheduled', 'repair', 'emergency'
    priority: str  # 'low', 'medium', 'high', 'critical'
    description: str
    estimated_duration: Optional[int] = None  # minutes
    required_materials: List[Dict[str, Any]] = Field(default_factory=list)

    @validator("maintenance_type")
    def validate_maintenance_type(cls, v):
        valid_types = ["scheduled", "repair", "emergency"]
        if v not in valid_types:
            raise ValueError(f"Maintenance type must be one of: {valid_types}")
        return v

    @validator("priority")
    def validate_priority(cls, v):
        valid_priorities = ["low", "medium", "high", "critical"]
        if v not in valid_priorities:
            raise ValueError(f"Priority must be one of: {valid_priorities}")
        return v

    @property
    def is_urgent(self) -> bool:
        """Check if maintenance is urgent."""
        return self.priority in ["high", "critical"]

    @property
    def can_wait(self) -> bool:
        """Check if maintenance can be scheduled later."""
        return self.maintenance_type == "scheduled" and self.priority == "low"


class DeviceCommandModel(BaseModel):
    """Device command domain model."""

    device_id: int
    command_type: str  # 'refill', 'clean', 'restart', 'update_firmware'
    parameters: Dict[str, Any] = Field(default_factory=dict)
    priority: str = "normal"  # 'low', 'normal', 'high'
    timeout_seconds: int = 300

    @validator("command_type")
    def validate_command_type(cls, v):
        valid_commands = ["refill", "clean", "restart", "update_firmware", "status_check"]
        if v not in valid_commands:
            raise ValueError(f"Command type must be one of: {valid_commands}")
        return v

    @validator("priority")
    def validate_priority(cls, v):
        valid_priorities = ["low", "normal", "high"]
        if v not in valid_priorities:
            raise ValueError(f"Priority must be one of: {valid_priorities}")
        return v

    def can_execute_on_device(self, device: DeviceModel) -> tuple[bool, Optional[str]]:
        """Check if command can be executed on device."""
        if not device.is_online:
            return False, "Device is not online"

        if device.status == "maintenance":
            return False, "Device is under maintenance"

        # Specific command validations
        if self.command_type == "refill" and "material_id" not in self.parameters:
            return False, "Material ID required for refill command"

        return True, None
