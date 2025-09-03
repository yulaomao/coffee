"""
Unified Data Generator for Coffee Machine Management System.
Provides consistent, idempotent demo data generation for different scenarios.

Features:
- Idempotent execution (can be run multiple times safely)
- Support for different scenarios (production, development, demo)
- Consistent data relationships
- Configurable scale and parameters
"""

import hashlib
import os
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from faker import Faker

# Import database components
from app import create_app
from app.extensions import db
from app.models import (
    Device,
    DeviceBin,
    DeviceMaterial,
    DeviceStatusLog,
    Fault,
    MaterialCatalog,
    Merchant,
    Order,
    Product,
    Role,
    User,
    WorkOrder,
)


class DataGenerator:
    """Unified data generator for all demo scenarios."""

    def __init__(self, scenario: str = "demo"):
        """Initialize data generator.

        Args:
            scenario: 'production', 'development', or 'demo'
        """
        self.scenario = scenario
        self.fake = Faker("zh_CN")
        self.app = create_app()

        # Configuration based on scenario
        self.config = self._get_scenario_config(scenario)

        # Track generated data for consistency
        self._generated_data = {}

    def _get_scenario_config(self, scenario: str) -> Dict[str, Any]:
        """Get configuration for specific scenario."""
        configs = {
            "production": {
                "merchants": 3,
                "devices_per_merchant": 5,
                "users_per_merchant": 2,
                "orders_per_device": 50,
                "fault_rate": 0.02,
                "online_rate": 0.95,
                "material_variety": 8,
                "demo_prefix": "PROD",
            },
            "development": {
                "merchants": 2,
                "devices_per_merchant": 3,
                "users_per_merchant": 2,
                "orders_per_device": 20,
                "fault_rate": 0.1,
                "online_rate": 0.8,
                "material_variety": 6,
                "demo_prefix": "DEV",
            },
            "demo": {
                "merchants": 5,
                "devices_per_merchant": 10,
                "users_per_merchant": 3,
                "orders_per_device": 100,
                "fault_rate": 0.05,
                "online_rate": 0.85,
                "material_variety": 12,
                "demo_prefix": "DEMO",
            },
        }
        return configs.get(scenario, configs["demo"])

    def generate_all(self, force: bool = False) -> Dict[str, Any]:
        """Generate all demo data.

        Args:
            force: If True, clear existing demo data first

        Returns:
            Dictionary with generation statistics
        """
        with self.app.app_context():
            if force:
                self.clear_demo_data()

            # Check if data already exists (idempotent)
            if self._demo_data_exists() and not force:
                return {"message": "Demo data already exists", "skipped": True}

            stats = {}

            # Generate base data
            stats["materials"] = self._generate_materials()
            stats["merchants"] = self._generate_merchants()
            stats["users"] = self._generate_users()
            stats["products"] = self._generate_products()

            # Generate operational data
            stats["devices"] = self._generate_devices()
            stats["device_materials"] = self._generate_device_materials()
            stats["orders"] = self._generate_orders()
            stats["faults"] = self._generate_faults()

            db.session.commit()

            return {
                "scenario": self.scenario,
                "generated": True,
                "statistics": stats,
                "timestamp": datetime.utcnow().isoformat(),
            }

    def _demo_data_exists(self) -> bool:
        """Check if demo data already exists."""
        prefix = self.config["demo_prefix"]
        return Device.query.filter(Device.device_no.like(f"{prefix}-%")).count() > 0

    def clear_demo_data(self) -> Dict[str, int]:
        """Clear existing demo data."""
        prefix = self.config["demo_prefix"]

        # Get demo devices
        demo_devices = Device.query.filter(Device.device_no.like(f"{prefix}-%")).all()
        demo_device_ids = [d.id for d in demo_devices]

        deleted_counts = {}

        if demo_device_ids:
            # Delete related data
            deleted_counts["orders"] = Order.query.filter(
                Order.device_id.in_(demo_device_ids)
            ).delete(synchronize_session=False)

            deleted_counts["faults"] = Fault.query.filter(
                Fault.device_id.in_(demo_device_ids)
            ).delete(synchronize_session=False)

            deleted_counts["work_orders"] = WorkOrder.query.filter(
                WorkOrder.device_id.in_(demo_device_ids)
            ).delete(synchronize_session=False)

            deleted_counts["device_materials"] = DeviceMaterial.query.filter(
                DeviceMaterial.device_id.in_(demo_device_ids)
            ).delete(synchronize_session=False)

            deleted_counts["device_bins"] = DeviceBin.query.filter(
                DeviceBin.device_id.in_(demo_device_ids)
            ).delete(synchronize_session=False)

            deleted_counts["device_status_logs"] = DeviceStatusLog.query.filter(
                DeviceStatusLog.device_id.in_(demo_device_ids)
            ).delete(synchronize_session=False)

            # Delete devices
            deleted_counts["devices"] = Device.query.filter(
                Device.device_no.like(f"{prefix}-%")
            ).delete(synchronize_session=False)

        # Delete demo merchants and users
        demo_merchants = Merchant.query.filter(Merchant.name.like(f"{prefix}%")).all()
        demo_merchant_ids = [m.id for m in demo_merchants]

        if demo_merchant_ids:
            deleted_counts["users"] = User.query.filter(
                User.merchant_id.in_(demo_merchant_ids)
            ).delete(synchronize_session=False)

            deleted_counts["merchants"] = Merchant.query.filter(
                Merchant.name.like(f"{prefix}%")
            ).delete(synchronize_session=False)

        db.session.commit()
        return deleted_counts

    def _generate_materials(self) -> int:
        """Generate material catalog."""
        materials_data = [
            ("MAT001", "精品咖啡豆", "bean", "g", 1000),
            ("MAT002", "新鲜牛奶", "milk", "ml", 2000),
            ("MAT003", "香草糖浆", "syrup", "ml", 500),
            ("MAT004", "一次性纸杯", "cup", "个", 200),
            ("MAT005", "焦糖糖浆", "syrup", "ml", 500),
            ("MAT006", "榛果糖浆", "syrup", "ml", 500),
            ("MAT007", "椰浆", "milk", "ml", 1000),
            ("MAT008", "可可粉", "powder", "g", 300),
            ("MAT009", "奶泡粉", "powder", "g", 500),
            ("MAT010", "饮品盖", "accessory", "个", 200),
            ("MAT011", "搅拌棒", "accessory", "个", 500),
            ("MAT012", "清洁片", "maintenance", "片", 50),
        ]

        count = 0
        for code, name, category, unit, capacity in materials_data:
            if not MaterialCatalog.query.filter_by(code=code).first():
                material = MaterialCatalog(
                    code=code,
                    name=name,
                    category=category,
                    unit=unit,
                    default_capacity=capacity,
                    is_active=True,
                )
                db.session.add(material)
                count += 1

        return count

    def _generate_merchants(self) -> int:
        """Generate merchants."""
        count = 0
        prefix = self.config["demo_prefix"]

        for i in range(1, self.config["merchants"] + 1):
            merchant_name = f"{prefix}商户{i:02d}"

            if not Merchant.query.filter_by(name=merchant_name).first():
                merchant = Merchant(name=merchant_name)
                db.session.add(merchant)
                db.session.flush()  # Get ID
                self._generated_data[f"merchant_{i}"] = merchant
                count += 1

        return count

    def _generate_users(self) -> int:
        """Generate users for merchants."""
        count = 0
        prefix = self.config["demo_prefix"]

        merchants = Merchant.query.filter(Merchant.name.like(f"{prefix}%")).all()
        roles = ["merchant_admin", "ops_engineer", "viewer"]

        for merchant in merchants:
            for j in range(self.config["users_per_merchant"]):
                username = f"{prefix.lower()}_user_{merchant.id}_{j+1}"

                if not User.query.filter_by(username=username).first():
                    user = User(
                        username=username,
                        email=f"{username}@example.com",
                        role=random.choice(roles),
                        merchant_id=merchant.id,
                        is_active=True,
                    )
                    user.set_password("demo123")
                    db.session.add(user)
                    count += 1

        return count

    def _generate_products(self) -> int:
        """Generate product catalog."""
        products_data = [
            ("美式咖啡", "经典美式黑咖啡", 15.0),
            ("拿铁", "香浓牛奶拿铁", 22.0),
            ("卡布奇诺", "意式卡布奇诺", 20.0),
            ("焦糖玛奇朵", "香甜焦糖玛奇朵", 25.0),
            ("香草拿铁", "香草风味拿铁", 24.0),
            ("摩卡", "巧克力摩卡咖啡", 26.0),
            ("榛果拿铁", "榛果风味拿铁", 24.0),
            ("椰香拿铁", "椰浆拿铁", 23.0),
        ]

        count = 0
        for name, desc, price in products_data:
            if not Product.query.filter_by(name=name).first():
                product = Product(name=name, description=desc, price=price, is_active=True)
                db.session.add(product)
                count += 1

        return count

    def _generate_devices(self) -> int:
        """Generate devices for merchants."""
        count = 0
        prefix = self.config["demo_prefix"]

        merchants = Merchant.query.filter(Merchant.name.like(f"{prefix}%")).all()
        locations = [
            "大厅",
            "二楼",
            "员工区",
            "VIP区",
            "休息区",
            "会议室",
            "前台",
            "咖啡厅",
            "接待室",
            "办公区",
        ]

        for merchant in merchants:
            for i in range(self.config["devices_per_merchant"]):
                device_no = f"{prefix}-{merchant.id:02d}-{i+1:03d}"

                if not Device.query.filter_by(device_no=device_no).first():
                    # Determine status based on online rate
                    if random.random() < self.config["online_rate"]:
                        status = "online"
                    else:
                        status = random.choice(["offline", "fault"])

                    device = Device(
                        device_no=device_no,
                        address_detail=random.choice(locations),
                        status=status,
                        merchant_id=merchant.id,
                    )
                    db.session.add(device)
                    count += 1

        return count

    def _generate_device_materials(self) -> int:
        """Generate device material configurations."""
        count = 0
        prefix = self.config["demo_prefix"]

        devices = Device.query.filter(Device.device_no.like(f"{prefix}-%")).all()
        materials = (
            MaterialCatalog.query.filter_by(is_active=True)
            .limit(self.config["material_variety"])
            .all()
        )

        for device in devices:
            # Each device gets 4-6 materials
            device_materials = random.sample(materials, min(random.randint(4, 6), len(materials)))

            for material in device_materials:
                if not DeviceMaterial.query.filter_by(
                    device_id=device.id, material_id=material.id
                ).first():
                    capacity = material.default_capacity or 100.0
                    threshold = capacity * 0.2  # 20% threshold

                    # Random current stock (some might be low for demo purposes)
                    if random.random() < 0.15:  # 15% chance of low stock
                        remain = random.uniform(0, threshold)
                    else:
                        remain = random.uniform(threshold, capacity)

                    device_material = DeviceMaterial(
                        device_id=device.id,
                        material_id=material.id,
                        remain=remain,
                        capacity=capacity,
                        threshold=threshold,
                    )
                    db.session.add(device_material)
                    count += 1

        return count

    def _generate_orders(self) -> int:
        """Generate order history."""
        count = 0
        prefix = self.config["demo_prefix"]

        devices = Device.query.filter(Device.device_no.like(f"{prefix}-%")).all()
        products = Product.query.filter_by(is_active=True).all()

        # Generate orders over the last 30 days
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)

        for device in devices:
            orders_count = self.config["orders_per_device"]

            for _ in range(orders_count):
                # Random timestamp in the last 30 days
                order_time = start_date + timedelta(
                    seconds=random.randint(0, int((end_date - start_date).total_seconds()))
                )

                product = random.choice(products)
                quantity = random.choice([1, 1, 1, 2, 2])  # Most orders are single items

                # Payment status (90% paid for demo)
                pay_status = (
                    "paid" if random.random() < 0.9 else random.choice(["pending", "cancelled"])
                )

                order = Order(
                    device_id=device.id,
                    merchant_id=device.merchant_id,
                    product_id=product.id,
                    qty=quantity,
                    unit_price=product.price,
                    total_amount=product.price * quantity,
                    pay_status=pay_status,
                    pay_method="wechat" if pay_status == "paid" else "cash",
                    created_at=order_time,
                )
                db.session.add(order)
                count += 1

        return count

    def _generate_faults(self) -> int:
        """Generate fault records."""
        count = 0
        prefix = self.config["demo_prefix"]

        devices = Device.query.filter(Device.device_no.like(f"{prefix}-%")).all()
        fault_codes = [
            ("E001", "水位传感器异常", "warning"),
            ("E002", "加热模块故障", "error"),
            ("E003", "物料不足警告", "warning"),
            ("E004", "出料口堵塞", "error"),
            ("E005", "清洁提醒", "info"),
            ("E006", "支付模块异常", "error"),
            ("E007", "温度传感器故障", "warning"),
            ("E008", "网络连接异常", "warning"),
        ]

        for device in devices:
            # Each device might have 0-3 faults based on fault rate
            if random.random() < self.config["fault_rate"] * 10:  # Scale up for demo
                fault_count = random.randint(1, 3)

                for _ in range(fault_count):
                    code, message, level = random.choice(fault_codes)

                    # Random fault time in the last 7 days
                    fault_time = datetime.utcnow() - timedelta(
                        seconds=random.randint(0, 7 * 24 * 3600)
                    )

                    fault = Fault(
                        device_id=device.id,
                        code=code,
                        level=level,
                        message=message,
                        created_at=fault_time,
                    )
                    db.session.add(fault)
                    count += 1

        return count

    def get_checksum(self) -> str:
        """Generate checksum for current scenario configuration."""
        config_str = str(sorted(self.config.items()))
        return hashlib.md5(config_str.encode()).hexdigest()[:8]


def main():
    """Command line interface for data generator."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate demo data for coffee machine system")
    parser.add_argument(
        "--scenario",
        choices=["production", "development", "demo"],
        default="demo",
        help="Scenario type",
    )
    parser.add_argument(
        "--force", action="store_true", help="Force regeneration (clear existing data)"
    )
    parser.add_argument("--clear-only", action="store_true", help="Only clear existing data")

    args = parser.parse_args()

    generator = DataGenerator(args.scenario)

    if args.clear_only:
        print(f"Clearing {args.scenario} data...")
        result = generator.clear_demo_data()
        print(f"Cleared data: {result}")
    else:
        print(f"Generating {args.scenario} data...")
        result = generator.generate_all(force=args.force)
        print(f"Generation result: {result}")


if __name__ == "__main__":
    main()
