from __future__ import annotations

from typing import Optional

from ..extensions import db
from ..models import Device, DeviceBin, DeviceMaterial, MaterialCatalog
from .material_definitions import DEFAULT_DEVICE_BINS, DEFAULT_MATERIALS


def ensure_bootstrap_materials() -> None:
    """在应用启动时确保最小可用的物料与料盒数据。
    - 若物料字典为空：写入一组默认物料（含编码/单位/默认容量）
    - 为没有新表料盒(DeviceBin)记录的设备初始化 3 个槽位并绑定默认物料
    - 兼容旧表：为没有 DeviceMaterial 的设备补齐 3 条演示数据

    该函数应保持幂等，多次调用不会重复插入。
    """
    # 1) 物料字典
    if MaterialCatalog.query.count() == 0:
        for mid, code, name, cat, unit, defcap, description in DEFAULT_MATERIALS:
            db.session.add(
                MaterialCatalog(
                    id=mid,
                    code=code,
                    name=name,
                    category=cat,
                    unit=unit,
                    default_capacity=defcap,
                    description=description,
                    is_active=True,
                )
            )
        db.session.commit()

    # 2) 每台设备的料盒初始化（仅当该设备还没有任何 DeviceBin 记录时）
    mats = {m.code: m for m in MaterialCatalog.query.all()}
    for d in Device.query.all():
        if DeviceBin.query.filter_by(device_id=d.id).count() == 0:
            for bin_index, material_code, custom_label in DEFAULT_DEVICE_BINS:
                material = mats.get(material_code)
                if material:
                    db.session.add(
                        DeviceBin(
                            device_id=d.id,
                            bin_index=bin_index,
                            material_id=material.id,
                            capacity=material.default_capacity,
                            unit=material.unit,
                            custom_label=custom_label,
                        )
                    )
    db.session.commit()

    # 3) 旧模型的演示余量（仅用于旧页面 material_manage.html）
    for d in Device.query.all():
        if DeviceMaterial.query.filter_by(device_id=d.id).count() == 0:
            for mid in (1, 2, 3):
                db.session.add(
                    DeviceMaterial(
                        device_id=d.id, material_id=mid, remain=50.0, capacity=100.0, threshold=10.0
                    )
                )
    db.session.commit()
