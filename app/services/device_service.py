"""
Device Service for device-related business logic.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..models import Device, DeviceMaterial, MaterialCatalog
from ..repositories import DeviceMaterialRepository, DeviceRepository, MaterialRepository
from .base_service import BaseService


class DeviceService(BaseService):
    """Service for device-related business operations."""

    def __init__(self):
        super().__init__()
        self.device_repo = DeviceRepository()
        self.material_repo = MaterialRepository()
        self.device_material_repo = DeviceMaterialRepository()

    def get_device_dashboard_data(self, merchant_id: Optional[int] = None) -> Dict[str, Any]:
        """Get comprehensive device dashboard data."""
        # Device statistics
        device_stats = self.device_repo.get_device_statistics(merchant_id)

        # Material alerts
        material_alerts = self._get_material_alerts(merchant_id)

        return {"device_stats": device_stats, "material_alerts": material_alerts}

    def _get_material_alerts(self, merchant_id: Optional[int] = None) -> Dict[str, Any]:
        """Get material alert information."""
        # Critical alerts (below threshold)
        critical_materials = self.device_repo.get_devices_with_low_materials(1.0)

        # Warning alerts (slightly above threshold but concerning)
        warning_materials = self.device_repo.get_devices_with_low_materials(1.2)
        warning_materials = [m for m in warning_materials if m not in critical_materials]

        # Filter by merchant if specified
        if merchant_id:
            # This would need device filtering logic - simplified for now
            pass

        return {
            "critical_count": len(critical_materials),
            "warning_count": len(warning_materials),
            "critical_materials": critical_materials[:5],  # Top 5
            "warning_materials": warning_materials[:5],  # Top 5
        }

    def register_device(self, device_no: str, merchant_id: int, **kwargs) -> Device:
        """Register a new device."""
        # Check if device already exists
        existing = self.device_repo.find_by_device_no(device_no)
        if existing:
            raise ValueError(f"Device {device_no} already exists")

        device = self.device_repo.create(
            device_no=device_no, merchant_id=merchant_id, status="offline", **kwargs
        )

        self.commit()
        return device

    def setup_device_materials(
        self, device_id: int, material_configs: List[Dict[str, Any]]
    ) -> List[DeviceMaterial]:
        """Set up materials for a device."""
        device = self.device_repo.get_by_id(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")

        device_materials = []

        for config in material_configs:
            material_id = config["material_id"]
            capacity = config.get("capacity", 100.0)
            threshold = config.get("threshold", capacity * 0.2)
            initial_remain = config.get("initial_remain", capacity)

            # Check if material exists
            material = self.material_repo.get_by_id(material_id)
            if not material or not material.is_active:
                raise ValueError(f"Material {material_id} not found or inactive")

            # Create or update device material
            device_material = self.device_material_repo.find_device_material(device_id, material_id)
            if device_material:
                device_material = self.device_material_repo.update(
                    device_material, capacity=capacity, threshold=threshold, remain=initial_remain
                )
            else:
                device_material = self.device_material_repo.create(
                    device_id=device_id,
                    material_id=material_id,
                    capacity=capacity,
                    threshold=threshold,
                    remain=initial_remain,
                )

            device_materials.append(device_material)

        self.commit()
        return device_materials

    def update_device_status(self, device_id: int, status: str, **kwargs) -> Device:
        """Update device status with logging."""
        device = self.device_repo.update_device_status(device_id, status, **kwargs)
        if not device:
            raise ValueError(f"Device {device_id} not found")

        self.commit()
        return device

    def refill_material(
        self, device_id: int, material_id: int, amount: Optional[float] = None
    ) -> DeviceMaterial:
        """Refill material stock for a device."""
        device_material = self.device_material_repo.fill_material_stock(
            device_id, material_id, amount
        )
        if not device_material:
            raise ValueError(
                f"Device material not found: device={device_id}, material={material_id}"
            )

        self.commit()
        return device_material

    def consume_material(
        self, device_id: int, material_consumptions: Dict[int, float]
    ) -> List[DeviceMaterial]:
        """Consume materials for an order."""
        updated_materials = []

        for material_id, consumption in material_consumptions.items():
            device_material = self.device_material_repo.find_device_material(device_id, material_id)
            if not device_material:
                raise ValueError(f"Material {material_id} not configured for device {device_id}")

            if device_material.remain < consumption:
                raise ValueError(
                    f"Insufficient material {material_id}: need {consumption}, have {device_material.remain}"
                )

            new_remain = device_material.remain - consumption
            device_material = self.device_material_repo.update(device_material, remain=new_remain)
            updated_materials.append(device_material)

        self.commit()
        return updated_materials
