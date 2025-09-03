# -*- coding: utf-8 -*-
DEFAULT_MATERIALS = [
    (1, "bean-A", "Coffee Bean A", "bean", "g", 120.0, "Standard coffee bean"),
    (2, "milk-A", "Milk A", "milk", "g", 800.0, "Standard milk powder"),
    (3, "syrup-A", "Syrup A", "syrup", "ml", 1000.0, "Vanilla syrup"),
    (4, "cup-12oz", "Cup 12oz", "cup", "pcs", 100.0, "12oz paper cup"),
    (5, "stir-rod", "Stir Rod", "accessory", "pcs", 200.0, "Wooden stirrer"),
    (6, "bean-B", "Coffee Bean B", "bean", "g", 120.0, "Dark roast coffee bean"),
    (7, "milk-oat", "Oat Milk", "milk", "ml", 1000.0, "Plant-based oat milk"),
    (8, "syrup-caramel", "Caramel Syrup", "syrup", "ml", 1000.0, "Rich caramel syrup"),
    (9, "cup-8oz", "Cup 8oz", "cup", "pcs", 100.0, "8oz paper cup"),
    (10, "lid-dome", "Dome Lid", "accessory", "pcs", 100.0, "Transparent dome lid"),
]

DEFAULT_DEVICE_BINS = [
    (1, "bean-A", "Coffee Bean"),
    (2, "milk-A", "Milk Powder"),
    (3, "syrup-A", "Basic Syrup"),
]


def get_demo_materials():
    return [
        (mid, code, name, category, unit, capacity)
        for mid, code, name, category, unit, capacity, _ in DEFAULT_MATERIALS
    ]


def get_extended_demo_materials():
    return get_demo_materials()
