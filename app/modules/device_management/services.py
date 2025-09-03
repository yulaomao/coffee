"""
Device Management Service - Business Logic Layer
Implements domain-driven design patterns for device operations.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ...repositories import DeviceMaterialRepository, DeviceRepository, MaterialRepository
from ...schemas.device_schemas import (
    DeviceCreateSchema,
    DeviceMaterialSchema,
    DeviceResponseSchema,
    DeviceUpdateSchema,
    MaterialRefillSchema,
)
from ...services import BaseService


class DeviceManagementService(BaseService):
    """Service for device management domain operations."""

    def __init__(self):
        super().__init__()
        self.device_repo = DeviceRepository()
        self.material_repo = MaterialRepository()
        self.device_material_repo = DeviceMaterialRepository()

    def register_new_device(
        self,
        device_data: DeviceCreateSchema,
        initial_materials: Optional[List[DeviceMaterialSchema]] = None,
    ) -> DeviceResponseSchema:
        """Register a new device with optional initial material setup."""
        try:
            # Validate device doesn't exist
            existing = self.device_repo.find_by_device_no(device_data.device_no)
            if existing:
                raise ValueError(f"Device {device_data.device_no} already exists")

            # Create device
            device = self.device_repo.create(**device_data.model_dump())
            self.flush()

            # Setup initial materials if provided
            if initial_materials:
                for material_config in initial_materials:
                    self._setup_device_material(device.id, material_config)

            self.commit()

            return DeviceResponseSchema.model_validate(device)

        except Exception as e:
            self.rollback()
            raise e

    def update_device_information(
        self, device_id: int, update_data: DeviceUpdateSchema
    ) -> DeviceResponseSchema:
        """Update device information."""
        device = self.device_repo.get_by_id(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")

        # Only update provided fields
        update_dict = update_data.model_dump(exclude_unset=True)
        device = self.device_repo.update(device, **update_dict)
        self.commit()

        return DeviceResponseSchema.model_validate(device)

    def get_device_dashboard(self, merchant_id: Optional[int] = None) -> Dict[str, Any]:
        """Get comprehensive device dashboard data."""
        device_stats = self.device_repo.get_device_statistics(merchant_id)

        # Get material alerts
        critical_materials = self.device_repo.get_devices_with_low_materials(1.0)
        warning_materials = self.device_repo.get_devices_with_low_materials(1.2)

        # Filter critical from warning
        critical_device_material_pairs = {(m.device_id, m.material_id) for m in critical_materials}
        warning_materials = [
            m
            for m in warning_materials
            if (m.device_id, m.material_id) not in critical_device_material_pairs
        ]

        return {
            "device_statistics": device_stats,
            "material_alerts": {
                "critical": {"count": len(critical_materials), "items": critical_materials[:5]},
                "warning": {"count": len(warning_materials), "items": warning_materials[:5]},
            },
            "status_distribution": self._get_status_distribution(merchant_id),
        }

    def perform_material_refill(
        self, device_id: int, refill_data: MaterialRefillSchema
    ) -> Dict[str, Any]:
        """Perform material refill operation."""
        device = self.device_repo.get_by_id(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")

        # Get material info
        material = self.material_repo.get_by_id(refill_data.material_id)
        if not material or not material.is_active:
            raise ValueError(f"Material {refill_data.material_id} not found or inactive")

        # Perform refill
        device_material = self.device_material_repo.fill_material_stock(
            device_id, refill_data.material_id, refill_data.amount
        )

        if not device_material:
            raise ValueError(
                f"Material {refill_data.material_id} not configured for device {device_id}"
            )

        self.commit()

        return {
            "device_id": device_id,
            "material_id": refill_data.material_id,
            "material_name": material.name,
            "previous_amount": device_material.remain - (refill_data.amount or 0),
            "current_amount": device_material.remain,
            "capacity": device_material.capacity,
            "refill_amount": refill_data.amount
            or (device_material.capacity - device_material.remain),
        }

    def get_device_health_report(self, device_id: int, days: int = 7) -> Dict[str, Any]:
        """Generate comprehensive device health report."""
        device = self.device_repo.get_by_id(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")

        # Get status history
        status_logs = self.device_repo.get_device_status_history(device_id, days)

        # Get material levels
        device_materials = self.device_material_repo.find_by_device(device_id)

        # Calculate health metrics
        uptime_percentage = self._calculate_uptime(status_logs, days)
        material_health = self._assess_material_health(device_materials)

        return {
            "device_info": DeviceResponseSchema.model_validate(device).model_dump(),
            "health_score": self._calculate_health_score(uptime_percentage, material_health),
            "uptime_percentage": uptime_percentage,
            "material_health": material_health,
            "status_history": [
                {
                    "timestamp": log.created_at.isoformat(),
                    "status": log.status,
                    "payload": log.payload,
                }
                for log in status_logs
            ],
            "recommendations": self._generate_maintenance_recommendations(
                device, device_materials, status_logs
            ),
        }

    def _setup_device_material(self, device_id: int, material_config: DeviceMaterialSchema):
        """Setup material configuration for a device."""
        # Validate material exists and is active
        material = self.material_repo.get_by_id(material_config.material_id)
        if not material or not material.is_active:
            raise ValueError(f"Material {material_config.material_id} not found or inactive")

        # Create or update device material
        device_material = self.device_material_repo.find_device_material(
            device_id, material_config.material_id
        )

        if device_material:
            self.device_material_repo.update(
                device_material,
                capacity=material_config.capacity,
                threshold=material_config.threshold,
                remain=material_config.remain or material_config.capacity,
            )
        else:
            self.device_material_repo.create(
                device_id=device_id,
                material_id=material_config.material_id,
                capacity=material_config.capacity,
                threshold=material_config.threshold,
                remain=material_config.remain or material_config.capacity,
            )

    def _get_status_distribution(self, merchant_id: Optional[int]) -> Dict[str, int]:
        """Get device status distribution."""
        # This would ideally use the repository to get status counts
        # For now, using the existing statistics method
        stats = self.device_repo.get_device_statistics(merchant_id)
        return {
            "online": stats["online"],
            "offline": stats["offline"],
            "fault": stats["fault"],
            "total": stats["total"],
        }

    def _calculate_uptime(self, status_logs: List, days: int) -> float:
        """Calculate device uptime percentage."""
        if not status_logs:
            return 0.0

        # Simple uptime calculation - count online status logs
        online_logs = [log for log in status_logs if log.status == "online"]
        total_logs = len(status_logs)

        if total_logs == 0:
            return 0.0

        return round((len(online_logs) / total_logs) * 100, 2)

    def _assess_material_health(self, device_materials: List) -> Dict[str, Any]:
        """Assess overall material health for a device."""
        if not device_materials:
            return {"status": "unknown", "critical_count": 0, "warning_count": 0}

        critical_count = 0
        warning_count = 0

        for dm in device_materials:
            if dm.remain <= dm.threshold:
                critical_count += 1
            elif dm.remain <= dm.threshold * 1.5:
                warning_count += 1

        # Determine overall status
        if critical_count > 0:
            status = "critical"
        elif warning_count > 0:
            status = "warning"
        else:
            status = "healthy"

        return {
            "status": status,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "total_materials": len(device_materials),
        }

    def _calculate_health_score(
        self, uptime_percentage: float, material_health: Dict[str, Any]
    ) -> int:
        """Calculate overall device health score (0-100)."""
        # Weight uptime as 60% and material health as 40%
        uptime_score = uptime_percentage * 0.6

        material_score = 0
        if material_health["status"] == "healthy":
            material_score = 40
        elif material_health["status"] == "warning":
            material_score = 25
        else:  # critical
            material_score = 10

        return int(min(uptime_score + material_score, 100))

    def _generate_maintenance_recommendations(
        self, device, device_materials: List, status_logs: List
    ) -> List[str]:
        """Generate maintenance recommendations based on device data."""
        recommendations = []

        # Material-based recommendations
        for dm in device_materials:
            if dm.remain <= dm.threshold:
                recommendations.append(
                    f"立即补充 {dm.material_id} 号物料，当前余量 {dm.remain:.1f}，低于告警线 {dm.threshold:.1f}"
                )
            elif dm.remain <= dm.threshold * 1.2:
                recommendations.append(f"建议尽快补充 {dm.material_id} 号物料，余量较低")

        # Status-based recommendations
        offline_logs = [log for log in status_logs if log.status == "offline"]
        fault_logs = [log for log in status_logs if log.status == "fault"]

        if len(offline_logs) > len(status_logs) * 0.3:
            recommendations.append("设备离线时间较长，建议检查网络连接和电源状态")

        if fault_logs:
            recommendations.append("设备近期出现故障，建议安排维护检查")

        if not recommendations:
            recommendations.append("设备运行状态良好，建议定期维护保养")

        return recommendations
