"""集中化物料定义模块，统一管理所有物料相关的默认数据。

该模块提供：
1. 标准物料目录定义
2. 设备料盒默认配置
3. 确保所有初始化路径使用一致的物料数据
"""
from __future__ import annotations
from typing import List, Tuple, Dict, Any


# 标准物料目录定义 (id, code, name, category, unit, default_capacity, description)
DEFAULT_MATERIALS: List[Tuple[int, str, str, str, str, float, str]] = [
    (1, "bean-A", "咖啡豆", "bean", "g", 120.0, "标准阿拉比卡咖啡豆"),
    (2, "milk-A", "奶粉", "milk", "g", 800.0, "全脂奶粉"),
    (3, "syrup-A", "糖浆", "syrup", "ml", 1000.0, "香草风味糖浆"),
    (4, "cup-12oz", "纸杯", "cup", "pcs", 100.0, "12盎司一次性纸杯"),
    (5, "stir-rod", "搅拌棒", "accessory", "pcs", 200.0, "木质搅拌棒"),
]


# 设备料盒默认配置 (bin_index, material_code, custom_label)
DEFAULT_DEVICE_BINS: List[Tuple[int, str, str]] = [
    (1, "bean-A", "咖啡豆"),
    (2, "milk-A", "奶粉"),
    (3, "syrup-A", "糖浆"),
]


def get_material_by_code(code: str) -> Tuple[int, str, str, str, str, float, str] | None:
    """通过物料编码获取物料定义。"""
    for material in DEFAULT_MATERIALS:
        if material[1] == code:  # code is at index 1
            return material
    return None


def get_materials_dict() -> Dict[str, Dict[str, Any]]:
    """获取物料字典，以编码为键。"""
    result = {}
    for mid, code, name, category, unit, capacity, description in DEFAULT_MATERIALS:
        result[code] = {
            'id': mid,
            'code': code,
            'name': name,
            'category': category,
            'unit': unit,
            'default_capacity': capacity,
            'description': description,
        }
    return result


def get_demo_materials() -> List[Tuple[int, str, str, str, str, float]]:
    """获取演示用物料列表，不包含描述字段以保持向后兼容。"""
    return [(mid, code, name, category, unit, capacity) 
            for mid, code, name, category, unit, capacity, _ in DEFAULT_MATERIALS]


def get_extended_demo_materials() -> List[Tuple[int, str, str, str, str, float]]:
    """获取扩展的演示物料列表，包含更多种类用于大规模演示。"""
    extended = get_demo_materials() + [
        (6, "bean-B", "深烘咖啡豆", "bean", "g", 120.0),
        (7, "milk-oat", "燕麦奶", "milk", "ml", 1000.0),
        (8, "syrup-caramel", "焦糖糖浆", "syrup", "ml", 1000.0),
        (9, "cup-8oz", "小纸杯", "cup", "pcs", 100.0),
        (10, "lid-dome", "拱形杯盖", "accessory", "pcs", 100.0),
    ]
    return extended