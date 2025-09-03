"""
Material Repository implementation with material-specific operations.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import and_, desc, func

from ..models import DeviceMaterial, MaterialCatalog
from .base_repository import BaseRepository


class MaterialRepository(BaseRepository[MaterialCatalog]):
    """Repository for Material-specific operations."""

    def __init__(self):
        from ..models import MaterialCatalog

        super().__init__(MaterialCatalog)

    def find_active_materials(self) -> List[MaterialCatalog]:
        """Find all active materials."""
        return self.find_by(is_active=True)

    def find_by_code(self, code: str) -> Optional[MaterialCatalog]:
        """Find material by code."""
        return self.find_one_by(code=code)

    def find_by_category(self, category: str) -> List[MaterialCatalog]:
        """Find materials by category."""
        return self.find_by(category=category, is_active=True)

    def get_material_usage_stats(self, material_id: int) -> Dict[str, Any]:
        """Get usage statistics for a material across all devices."""
        usage_data = (
            self.session.query(
                func.count(DeviceMaterial.id).label("device_count"),
                func.sum(DeviceMaterial.remain).label("total_remain"),
                func.sum(DeviceMaterial.capacity).label("total_capacity"),
                func.avg(DeviceMaterial.remain).label("avg_remain"),
                func.min(DeviceMaterial.remain).label("min_remain"),
                func.max(DeviceMaterial.remain).label("max_remain"),
            )
            .filter(DeviceMaterial.material_id == material_id)
            .first()
        )

        return {
            "device_count": usage_data.device_count or 0,
            "total_remain": float(usage_data.total_remain) if usage_data.total_remain else 0.0,
            "total_capacity": (
                float(usage_data.total_capacity) if usage_data.total_capacity else 0.0
            ),
            "avg_remain": float(usage_data.avg_remain) if usage_data.avg_remain else 0.0,
            "min_remain": float(usage_data.min_remain) if usage_data.min_remain else 0.0,
            "max_remain": float(usage_data.max_remain) if usage_data.max_remain else 0.0,
        }

    def get_low_stock_materials(self, threshold_multiplier: float = 1.0) -> List[Dict[str, Any]]:
        """Get materials that are running low across all devices."""
        return (
            self.session.query(
                MaterialCatalog.id.label("material_id"),
                MaterialCatalog.name.label("material_name"),
                MaterialCatalog.unit,
                func.count(DeviceMaterial.id).label("device_count"),
                func.sum(DeviceMaterial.remain).label("total_remain"),
                func.sum(DeviceMaterial.capacity).label("total_capacity"),
                func.avg(DeviceMaterial.remain / DeviceMaterial.threshold).label(
                    "avg_threshold_ratio"
                ),
            )
            .join(DeviceMaterial, MaterialCatalog.id == DeviceMaterial.material_id)
            .filter(
                and_(
                    MaterialCatalog.is_active == True,
                    DeviceMaterial.remain <= DeviceMaterial.threshold * threshold_multiplier,
                )
            )
            .group_by(MaterialCatalog.id, MaterialCatalog.name, MaterialCatalog.unit)
            .order_by(func.avg(DeviceMaterial.remain / DeviceMaterial.threshold).asc())
            .all()
        )


class DeviceMaterialRepository(BaseRepository[DeviceMaterial]):
    """Repository for DeviceMaterial-specific operations."""

    def __init__(self):
        from ..models import DeviceMaterial

        super().__init__(DeviceMaterial)

    def find_by_device(self, device_id: int) -> List[DeviceMaterial]:
        """Find all materials for a device."""
        return self.find_by(device_id=device_id)

    def find_device_material(self, device_id: int, material_id: int) -> Optional[DeviceMaterial]:
        """Find specific device-material relationship."""
        return self.find_one_by(device_id=device_id, material_id=material_id)

    def update_material_stock(
        self, device_id: int, material_id: int, remain: float
    ) -> Optional[DeviceMaterial]:
        """Update material stock for a device."""
        device_material = self.find_device_material(device_id, material_id)
        if device_material:
            return self.update(device_material, remain=remain)
        return None

    def fill_material_stock(
        self, device_id: int, material_id: int, fill_amount: float = None
    ) -> Optional[DeviceMaterial]:
        """Fill material stock to capacity or by specific amount."""
        device_material = self.find_device_material(device_id, material_id)
        if device_material:
            if fill_amount is None:
                # Fill to capacity
                new_remain = device_material.capacity
            else:
                # Add specific amount, capped at capacity
                new_remain = min(device_material.remain + fill_amount, device_material.capacity)
            return self.update(device_material, remain=new_remain)
        return None

    def get_materials_below_threshold(
        self, device_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get materials below threshold, optionally for a specific device."""
        query = (
            self.session.query(
                DeviceMaterial.device_id,
                DeviceMaterial.material_id,
                DeviceMaterial.remain,
                DeviceMaterial.threshold,
                DeviceMaterial.capacity,
                MaterialCatalog.name.label("material_name"),
                MaterialCatalog.unit,
            )
            .outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceMaterial.material_id)
            .filter(DeviceMaterial.remain <= DeviceMaterial.threshold)
        )

        if device_id:
            query = query.filter(DeviceMaterial.device_id == device_id)

        return query.order_by((DeviceMaterial.remain / DeviceMaterial.threshold).asc()).all()
