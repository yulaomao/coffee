from __future__ import annotations
from typing import Optional
from ..extensions import db
from ..models import MaterialCatalog, Device, DeviceBin, DeviceMaterial


def ensure_bootstrap_materials() -> None:
    """在应用启动时确保最小可用的物料与料盒数据。
    - 若物料字典为空：写入一组默认物料（含编码/单位/默认容量）
    - 为没有新表料盒(DeviceBin)记录的设备初始化 3 个槽位并绑定默认物料
    - 兼容旧表：为没有 DeviceMaterial 的设备补齐 3 条演示数据

    该函数应保持幂等，多次调用不会重复插入。
    """
    # 1) 物料字典
    if MaterialCatalog.query.count() == 0:
        defaults = [
            (1, "bean-A", "咖啡豆", "bean", "g", 120.0),
            (2, "milk-A", "奶粉", "milk", "g", 800.0),
            (3, "syrup-A", "糖浆", "syrup", "ml", 1000.0),
            (4, "cup-12oz", "纸杯", "cup", "pcs", 100.0),
            (5, "stir-rod", "搅拌棒", "accessory", "pcs", 200.0),
        ]
        for mid, code, name, cat, unit, defcap in defaults:
            db.session.add(MaterialCatalog(id=mid, code=code, name=name, category=cat, unit=unit, default_capacity=defcap, is_active=True))
        db.session.commit()

    # 2) 每台设备的料盒初始化（仅当该设备还没有任何 DeviceBin 记录时）
    mats = {m.code: m for m in MaterialCatalog.query.all()}
    for d in Device.query.all():
        if DeviceBin.query.filter_by(device_id=d.id).count() == 0:
            # bin1: bean-A, bin2: milk-A, bin3: syrup-A
            if mats.get("bean-A"):
                db.session.add(DeviceBin(device_id=d.id, bin_index=1, material_id=mats["bean-A"].id, capacity=mats["bean-A"].default_capacity, unit=mats["bean-A"].unit, custom_label="咖啡豆"))
            if mats.get("milk-A"):
                db.session.add(DeviceBin(device_id=d.id, bin_index=2, material_id=mats["milk-A"].id, capacity=mats["milk-A"].default_capacity, unit=mats["milk-A"].unit, custom_label="奶粉"))
            if mats.get("syrup-A"):
                db.session.add(DeviceBin(device_id=d.id, bin_index=3, material_id=mats["syrup-A"].id, capacity=mats["syrup-A"].default_capacity, unit=mats["syrup-A"].unit, custom_label="糖浆"))
    db.session.commit()

    # 3) 旧模型的演示余量（仅用于旧页面 material_manage.html）
    for d in Device.query.all():
        if DeviceMaterial.query.filter_by(device_id=d.id).count() == 0:
            for mid in (1, 2, 3):
                db.session.add(DeviceMaterial(device_id=d.id, material_id=mid, remain=50.0, capacity=100.0, threshold=10.0))
    db.session.commit()
