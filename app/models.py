"""SQLAlchemy 模型定义（SQLite 兼容）。
包含：users, roles, merchants, devices, device_status_logs, orders,
materials, device_materials, faults, work_orders, upgrade_packages,
package_files, remote_commands, command_results, operation_logs,
product_catalog, material_catalog

为简化演示，部分字段与约束做了最小可运行实现。
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import Index, UniqueConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON
from .extensions import db


# 辅助 mixin
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Merchant(db.Model, TimestampMixin):
    __tablename__ = "merchants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)

    users = relationship("User", back_populates="merchant")
    devices = relationship("Device", back_populates="merchant")


class Role(db.Model):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False, unique=True)


class User(db.Model, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    email: Mapped[Optional[str]] = mapped_column(nullable=True)
    role: Mapped[str] = mapped_column(nullable=False, index=True)  # superadmin/merchant_admin/ops_engineer/viewer/finance
    merchant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("merchants.id"), nullable=True, index=True)
    wx_bind_info: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    merchant = relationship("Merchant", back_populates="users")


class Product(db.Model, TimestampMixin):
    __tablename__ = "product_catalog"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    price: Mapped[float] = mapped_column(nullable=False, default=10.0)


class MaterialCatalog(db.Model, TimestampMixin):
    __tablename__ = "material_catalog"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False, unique=True)
    unit: Mapped[str] = mapped_column(nullable=False, default="g")


class Device(db.Model, TimestampMixin):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_no: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    model: Mapped[Optional[str]] = mapped_column(nullable=True)
    firmware_version: Mapped[Optional[str]] = mapped_column(nullable=True)
    last_seen: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)
    status: Mapped[str] = mapped_column(nullable=False, default="offline", index=True)
    location_lat: Mapped[Optional[float]] = mapped_column(nullable=True)
    location_lng: Mapped[Optional[float]] = mapped_column(nullable=True)
    address: Mapped[Optional[str]] = mapped_column(nullable=True)
    address_detail: Mapped[Optional[str]] = mapped_column(nullable=True)
    summary_address: Mapped[Optional[str]] = mapped_column(nullable=True)
    scene: Mapped[Optional[str]] = mapped_column(nullable=True)
    customer_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    custom_fields: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    merchant = relationship("Merchant", back_populates="devices")
    orders = relationship("Order", back_populates="device")


class DeviceStatusLog(db.Model, TimestampMixin):
    __tablename__ = "device_status_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(nullable=False)
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)


class Order(db.Model, TimestampMixin):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("product_catalog.id"), nullable=True)
    price: Mapped[float] = mapped_column(nullable=False, default=0.0)
    pay_method: Mapped[str] = mapped_column(nullable=False, default="cash")
    status: Mapped[str] = mapped_column(nullable=False, default="paid", index=True)
    is_exception: Mapped[bool] = mapped_column(nullable=False, default=False)
    raw_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    device = relationship("Device", back_populates="orders")


class Material(db.Model, TimestampMixin):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)


class DeviceMaterial(db.Model, TimestampMixin):
    __tablename__ = "device_materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material_catalog.id"), nullable=False, index=True)
    remain: Mapped[float] = mapped_column(nullable=False, default=0)
    capacity: Mapped[float] = mapped_column(nullable=False, default=100)
    threshold: Mapped[float] = mapped_column(nullable=False, default=10)

    __table_args__ = (
        UniqueConstraint("device_id", "material_id", name="uq_device_material"),
    )


class Fault(db.Model, TimestampMixin):
    __tablename__ = "faults"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    level: Mapped[str] = mapped_column(nullable=False, default="info")
    code: Mapped[str] = mapped_column(nullable=False)
    message: Mapped[str] = mapped_column(nullable=False)
    resolved: Mapped[bool] = mapped_column(nullable=False, default=False)


class WorkOrder(db.Model, TimestampMixin):
    __tablename__ = "work_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    fault_id: Mapped[Optional[int]] = mapped_column(ForeignKey("faults.id"), nullable=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    assigned_to_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(nullable=False, default="pending")
    note: Mapped[Optional[str]] = mapped_column(nullable=True)


class UpgradePackage(db.Model, TimestampMixin):
    __tablename__ = "upgrade_packages"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(nullable=False)
    file_path: Mapped[str] = mapped_column(nullable=False)
    md5: Mapped[str] = mapped_column(nullable=False)


class PackageFile(db.Model, TimestampMixin):
    __tablename__ = "package_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("upgrade_packages.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(nullable=False)
    path: Mapped[str] = mapped_column(nullable=False)


class RemoteCommand(db.Model, TimestampMixin):
    __tablename__ = "remote_commands"
    id: Mapped[int] = mapped_column(primary_key=True)
    command_id: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    command_type: Mapped[str] = mapped_column(nullable=False)
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    issued_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="pending")  # pending/sent/success/fail
    result_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    result_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    batch_info: Mapped[Optional[str]] = mapped_column(nullable=True)


class CommandResult(db.Model, TimestampMixin):
    __tablename__ = "command_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    command_id: Mapped[str] = mapped_column(nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    success: Mapped[bool] = mapped_column(nullable=False, default=True)
    message: Mapped[Optional[str]] = mapped_column(nullable=True)
    raw_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)


class OperationLog(db.Model, TimestampMixin):
    __tablename__ = "operation_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(nullable=False)
    target_type: Mapped[str] = mapped_column(nullable=False)
    target_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(nullable=True)


class CustomFieldConfig(db.Model, TimestampMixin):
    __tablename__ = "custom_field_config"
    id: Mapped[int] = mapped_column(primary_key=True)
    key_index: Mapped[int] = mapped_column(nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    title: Mapped[str] = mapped_column(nullable=False, default="自定义字段")
    __table_args__ = (
        UniqueConstraint("key_index", name="uq_custom_field_key"),
    )


# 常用索引
Index("ix_orders_created", Order.created_at)
Index("ix_faults_created", Fault.created_at)
Index("ix_work_orders_status", WorkOrder.status)
