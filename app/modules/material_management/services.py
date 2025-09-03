"""
Material Management Service - Business Logic Layer
Implements material inventory, catalog management, and supply chain operations.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ...repositories import DeviceMaterialRepository, DeviceRepository, MaterialRepository
from ...schemas.material_schemas import (
    MaterialCatalogCreateSchema,
    MaterialCatalogResponseSchema,
    MaterialCatalogUpdateSchema,
)
from ...services import BaseService


class MaterialManagementService(BaseService):
    """Service for material management domain operations."""

    def __init__(self):
        super().__init__()
        self.material_repo = MaterialRepository()
        self.device_material_repo = DeviceMaterialRepository()
        self.device_repo = DeviceRepository()

    def create_material(
        self, material_data: MaterialCatalogCreateSchema
    ) -> MaterialCatalogResponseSchema:
        """Create a new material in the catalog."""
        try:
            # Check if material code already exists
            if material_data.code:
                existing = self.material_repo.find_by_code(material_data.code)
                if existing:
                    raise ValueError(f"Material with code {material_data.code} already exists")

            # Check if material name already exists
            existing_name = self.material_repo.find_by(name=material_data.name)
            if existing_name:
                raise ValueError(f"Material with name '{material_data.name}' already exists")

            # Create material
            material = self.material_repo.create(**material_data.model_dump())
            self.commit()

            return MaterialCatalogResponseSchema.model_validate(material)

        except Exception as e:
            self.rollback()
            raise e

    def get_material_inventory_overview(self, merchant_id: Optional[int] = None) -> Dict[str, Any]:
        """Get comprehensive material inventory overview."""
        # Get all active materials
        materials = self.material_repo.find_active_materials()

        inventory_data = []
        total_materials = len(materials)
        critical_count = 0
        warning_count = 0

        for material in materials:
            # Get usage statistics across all devices
            usage_stats = self.material_repo.get_material_usage_stats(material.id)

            # Get low stock devices for this material
            low_stock_data = self.device_material_repo.get_materials_below_threshold()
            material_low_stock = [
                item for item in low_stock_data if item.material_id == material.id
            ]

            # Calculate alert levels
            critical_devices = len(
                [item for item in material_low_stock if item.remain <= item.threshold]
            )
            warning_devices = len(
                [
                    item
                    for item in material_low_stock
                    if item.remain <= item.threshold * 1.2 and item.remain > item.threshold
                ]
            )

            if critical_devices > 0:
                critical_count += 1
            elif warning_devices > 0:
                warning_count += 1

            inventory_data.append(
                {
                    "material_id": material.id,
                    "material_code": material.code,
                    "material_name": material.name,
                    "category": material.category,
                    "unit": material.unit,
                    "default_capacity": material.default_capacity,
                    "usage_stats": usage_stats,
                    "alert_summary": {
                        "critical_devices": critical_devices,
                        "warning_devices": warning_devices,
                        "total_devices": usage_stats["device_count"],
                    },
                }
            )

        return {
            "summary": {
                "total_materials": total_materials,
                "critical_materials": critical_count,
                "warning_materials": warning_count,
                "healthy_materials": total_materials - critical_count - warning_count,
            },
            "materials": inventory_data,
        }

    def get_supply_chain_analytics(
        self, days: int = 30, merchant_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get supply chain analytics and insights."""
        # This would typically involve more complex analytics
        # For now, providing basic consumption trends

        # Get materials with highest consumption
        high_consumption_materials = []

        # Get materials with frequent stockouts
        stockout_materials = self.device_material_repo.get_materials_below_threshold()

        # Group by material
        material_stockouts = {}
        for item in stockout_materials:
            if item.material_id not in material_stockouts:
                material_stockouts[item.material_id] = {
                    "material_name": item.material_name,
                    "unit": item.unit,
                    "devices_affected": 0,
                    "total_shortage": 0,
                }

            material_stockouts[item.material_id]["devices_affected"] += 1
            material_stockouts[item.material_id]["total_shortage"] += item.threshold - item.remain

        # Calculate reorder recommendations
        reorder_recommendations = self._generate_reorder_recommendations(material_stockouts)

        return {
            "time_period": {
                "days": days,
                "start_date": (datetime.utcnow() - timedelta(days=days)).isoformat(),
                "end_date": datetime.utcnow().isoformat(),
            },
            "stockout_analysis": material_stockouts,
            "reorder_recommendations": reorder_recommendations,
            "efficiency_metrics": self._calculate_efficiency_metrics(),
        }

    def generate_material_forecast(
        self, material_id: int, forecast_days: int = 30
    ) -> Dict[str, Any]:
        """Generate material consumption forecast."""
        material = self.material_repo.get_by_id(material_id)
        if not material:
            raise ValueError(f"Material {material_id} not found")

        # Get current usage across all devices
        usage_stats = self.material_repo.get_material_usage_stats(material_id)

        # Simple forecast calculation (in real implementation, use ML models)
        daily_consumption = usage_stats["total_capacity"] * 0.05  # Assume 5% daily consumption

        forecast_data = []
        current_stock = usage_stats["total_remain"]

        for day in range(forecast_days):
            predicted_stock = max(0, current_stock - (daily_consumption * (day + 1)))
            forecast_data.append(
                {
                    "date": (datetime.utcnow() + timedelta(days=day + 1)).date().isoformat(),
                    "predicted_stock": round(predicted_stock, 2),
                    "status": (
                        "critical"
                        if predicted_stock <= usage_stats["total_capacity"] * 0.1
                        else "normal"
                    ),
                }
            )

        # Calculate when material will be critically low
        critical_threshold = usage_stats["total_capacity"] * 0.1
        days_to_critical = int(current_stock / daily_consumption) if daily_consumption > 0 else None

        return {
            "material_info": {
                "id": material.id,
                "name": material.name,
                "unit": material.unit,
                "category": material.category,
            },
            "current_status": usage_stats,
            "forecast": forecast_data,
            "alerts": {
                "days_to_critical": days_to_critical,
                "reorder_recommended": days_to_critical is not None and days_to_critical <= 7,
                "recommended_order_quantity": self._calculate_recommended_order_quantity(
                    usage_stats, daily_consumption
                ),
            },
        }

    def perform_bulk_material_update(self, updates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Perform bulk material updates across multiple devices."""
        try:
            successful_updates = []
            failed_updates = []

            for update in updates:
                try:
                    device_id = update["device_id"]
                    material_id = update["material_id"]
                    new_remain = update["new_remain"]

                    # Validate device and material exist
                    device = self.device_repo.get_by_id(device_id)
                    if not device:
                        raise ValueError(f"Device {device_id} not found")

                    material = self.material_repo.get_by_id(material_id)
                    if not material:
                        raise ValueError(f"Material {material_id} not found")

                    # Update device material
                    result = self.device_material_repo.update_material_stock(
                        device_id, material_id, new_remain
                    )

                    if result:
                        successful_updates.append(
                            {
                                "device_id": device_id,
                                "material_id": material_id,
                                "previous_amount": result.remain - new_remain,
                                "new_amount": result.remain,
                            }
                        )
                    else:
                        failed_updates.append(
                            {
                                "device_id": device_id,
                                "material_id": material_id,
                                "error": "Device material configuration not found",
                            }
                        )

                except Exception as e:
                    failed_updates.append(
                        {
                            "device_id": update.get("device_id"),
                            "material_id": update.get("material_id"),
                            "error": str(e),
                        }
                    )

            self.commit()

            return {
                "successful_updates": len(successful_updates),
                "failed_updates": len(failed_updates),
                "details": {"successful": successful_updates, "failed": failed_updates},
            }

        except Exception as e:
            self.rollback()
            raise e

    def _generate_reorder_recommendations(self, material_stockouts: Dict) -> List[Dict[str, Any]]:
        """Generate reorder recommendations based on stockout analysis."""
        recommendations = []

        for material_id, stockout_data in material_stockouts.items():
            if stockout_data["devices_affected"] > 0:
                # Calculate recommended order quantity
                safety_multiplier = 1.5  # 50% safety buffer
                base_quantity = stockout_data["total_shortage"]
                recommended_quantity = base_quantity * safety_multiplier

                urgency = "high" if stockout_data["devices_affected"] > 5 else "medium"

                recommendations.append(
                    {
                        "material_id": material_id,
                        "material_name": stockout_data["material_name"],
                        "unit": stockout_data["unit"],
                        "urgency": urgency,
                        "devices_affected": stockout_data["devices_affected"],
                        "total_shortage": stockout_data["total_shortage"],
                        "recommended_quantity": round(recommended_quantity, 2),
                        "reason": f"{stockout_data['devices_affected']} devices are below threshold",
                    }
                )

        # Sort by urgency and number of devices affected
        recommendations.sort(
            key=lambda x: (x["urgency"] == "high", x["devices_affected"]), reverse=True
        )

        return recommendations

    def _calculate_efficiency_metrics(self) -> Dict[str, Any]:
        """Calculate material efficiency metrics."""
        # Get all device materials
        all_materials = self.material_repo.find_active_materials()

        total_materials = len(all_materials)
        well_stocked_count = 0

        for material in all_materials:
            usage_stats = self.material_repo.get_material_usage_stats(material.id)

            # Consider well-stocked if average remaining is > 50% of capacity
            if usage_stats["avg_remain"] > usage_stats["total_capacity"] * 0.5:
                well_stocked_count += 1

        efficiency_score = (
            (well_stocked_count / total_materials * 100) if total_materials > 0 else 0
        )

        return {
            "stock_efficiency_score": round(efficiency_score, 2),
            "well_stocked_materials": well_stocked_count,
            "total_materials": total_materials,
            "efficiency_rating": (
                "excellent"
                if efficiency_score >= 90
                else (
                    "good"
                    if efficiency_score >= 75
                    else "fair" if efficiency_score >= 60 else "poor"
                )
            ),
        }

    def _calculate_recommended_order_quantity(
        self, usage_stats: Dict[str, Any], daily_consumption: float
    ) -> float:
        """Calculate recommended order quantity for a material."""
        # Calculate for 30-day supply with 20% safety buffer
        monthly_consumption = daily_consumption * 30
        safety_buffer = monthly_consumption * 0.2
        current_stock = usage_stats["total_remain"]

        # Only recommend if current stock is below monthly consumption
        if current_stock >= monthly_consumption:
            return 0.0

        recommended = monthly_consumption + safety_buffer - current_stock
        return max(0, round(recommended, 2))
