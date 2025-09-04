"""
全局字典数据管理服务

管理物料、配方、包等全局字典数据，与设备作用域数据分离
"""
from __future__ import annotations
from typing import Dict, List, Optional, Any
from ..redis_adapters import datastore


class MaterialDictService:
    """物料字典服务"""
    
    @staticmethod
    def create_material(code: str, material_data: Dict[str, Any]) -> bool:
        """创建物料字典"""
        return datastore.set_material_dict(code, material_data)
    
    @staticmethod
    def get_material(code: str) -> Optional[Dict[str, Any]]:
        """获取物料信息"""
        return datastore.get_material_dict(code)
    
    @staticmethod
    def list_materials() -> List[Dict[str, Any]]:
        """获取所有物料列表"""
        material_codes = datastore.get_all_materials()
        materials = []
        for code in material_codes:
            material = datastore.get_material_dict(code)
            if material:
                materials.append(material)
        return materials
    
    @staticmethod
    def bootstrap_default_materials():
        """初始化默认物料"""
        default_materials = [
            {
                'code': 'coffee_bean_colombia',
                'name': '哥伦比亚咖啡豆',
                'category': '咖啡豆',
                'unit': 'g',
                'density': 0.6,
                'cost_per_unit': 0.08
            },
            {
                'code': 'coffee_bean_brazil',
                'name': '巴西咖啡豆',
                'category': '咖啡豆',
                'unit': 'g',
                'density': 0.58,
                'cost_per_unit': 0.06
            },
            {
                'code': 'milk_powder',
                'name': '奶粉',
                'category': '奶制品',
                'unit': 'g',
                'density': 0.5,
                'cost_per_unit': 0.12
            },
            {
                'code': 'sugar_white',
                'name': '白糖',
                'category': '调味品',
                'unit': 'g',
                'density': 0.8,
                'cost_per_unit': 0.01
            },
            {
                'code': 'cocoa_powder',
                'name': '可可粉',
                'category': '调味品',
                'unit': 'g',
                'density': 0.4,
                'cost_per_unit': 0.15
            }
        ]
        
        for material in default_materials:
            MaterialDictService.create_material(material['code'], material)


class RecipeDictService:
    """配方字典服务"""
    
    @staticmethod
    def create_recipe(recipe_id: str, recipe_data: Dict[str, Any]) -> bool:
        """创建配方定义"""
        redis = datastore._get_redis()
        key = datastore._global_key(f"dict:recipe:{recipe_id}")
        enabled_key = datastore._global_key("dict:recipe:enabled")
        
        pipe = redis.pipeline()
        pipe.hset(key, mapping=recipe_data)
        
        if recipe_data.get('enabled', False):
            pipe.sadd(enabled_key, recipe_id)
        
        return all(pipe.execute())
    
    @staticmethod
    def get_recipe(recipe_id: str) -> Optional[Dict[str, Any]]:
        """获取配方定义"""
        redis = datastore._get_redis()
        key = datastore._global_key(f"dict:recipe:{recipe_id}")
        return redis.hgetall(key) or None
    
    @staticmethod
    def list_enabled_recipes() -> List[str]:
        """获取启用的配方ID列表"""
        redis = datastore._get_redis()
        enabled_key = datastore._global_key("dict:recipe:enabled")
        return list(redis.smembers(enabled_key))
    
    @staticmethod
    def enable_recipe(recipe_id: str) -> bool:
        """启用配方"""
        redis = datastore._get_redis()
        enabled_key = datastore._global_key("dict:recipe:enabled")
        return redis.sadd(enabled_key, recipe_id) >= 0
    
    @staticmethod
    def disable_recipe(recipe_id: str) -> bool:
        """禁用配方"""
        redis = datastore._get_redis()
        enabled_key = datastore._global_key("dict:recipe:enabled")
        return redis.srem(enabled_key, recipe_id) >= 0
    
    @staticmethod
    def bootstrap_default_recipes():
        """初始化默认配方"""
        default_recipes = [
            {
                'id': 'latte',
                'name': '拿铁',
                'description': '香浓拿铁咖啡',
                'enabled': True,
                'category': '咖啡',
                'price': 12.5,
                'preparation_time': 60,
                'ingredients': [
                    {'material_code': 'coffee_bean_colombia', 'amount': 18},
                    {'material_code': 'milk_powder', 'amount': 8}
                ],
                'steps': [
                    {'type': 'grind_beans', 'params': {'amount': 18, 'fineness': 'medium'}},
                    {'type': 'brew_espresso', 'params': {'water_temp': 92, 'pressure': 9}},
                    {'type': 'steam_milk', 'params': {'temperature': 65, 'foam_level': 'medium'}},
                    {'type': 'combine', 'params': {'method': 'pour'}}
                ]
            },
            {
                'id': 'americano',
                'name': '美式咖啡',
                'description': '经典美式黑咖啡',
                'enabled': True,
                'category': '咖啡',
                'price': 8.0,
                'preparation_time': 30,
                'ingredients': [
                    {'material_code': 'coffee_bean_colombia', 'amount': 20}
                ],
                'steps': [
                    {'type': 'grind_beans', 'params': {'amount': 20, 'fineness': 'medium-coarse'}},
                    {'type': 'brew_americano', 'params': {'water_temp': 96, 'water_amount': 150}}
                ]
            },
            {
                'id': 'cappuccino',
                'name': '卡布奇诺',
                'description': '意式卡布奇诺',
                'enabled': True,
                'category': '咖啡',
                'price': 14.0,
                'preparation_time': 80,
                'ingredients': [
                    {'material_code': 'coffee_bean_colombia', 'amount': 18},
                    {'material_code': 'milk_powder', 'amount': 6}
                ],
                'steps': [
                    {'type': 'grind_beans', 'params': {'amount': 18, 'fineness': 'fine'}},
                    {'type': 'brew_espresso', 'params': {'water_temp': 92, 'pressure': 9}},
                    {'type': 'steam_milk', 'params': {'temperature': 65, 'foam_level': 'high'}},
                    {'type': 'combine', 'params': {'method': 'layer'}}
                ]
            }
        ]
        
        for recipe in default_recipes:
            RecipeDictService.create_recipe(recipe['id'], recipe)


class PackageDictService:
    """包字典服务"""
    
    @staticmethod
    def create_package(package_id: str, package_data: Dict[str, Any]) -> bool:
        """创建包定义"""
        redis = datastore._get_redis()
        key = datastore._global_key(f"dict:package:{package_id}")
        
        # 按类型分组索引
        package_type = package_data.get('type', 'unknown')
        type_key = datastore._global_key(f"dict:package:type:{package_type}")
        
        pipe = redis.pipeline()
        pipe.hset(key, mapping=package_data)
        pipe.sadd(type_key, package_id)
        
        return all(pipe.execute())
    
    @staticmethod
    def get_package(package_id: str) -> Optional[Dict[str, Any]]:
        """获取包定义"""
        redis = datastore._get_redis()
        key = datastore._global_key(f"dict:package:{package_id}")
        return redis.hgetall(key) or None
    
    @staticmethod
    def list_packages_by_type(package_type: str) -> List[str]:
        """按类型获取包ID列表"""
        redis = datastore._get_redis()
        type_key = datastore._global_key(f"dict:package:type:{package_type}")
        return list(redis.smembers(type_key))
    
    @staticmethod
    def bootstrap_default_packages():
        """初始化默认包"""
        default_packages = [
            {
                'id': 'coffee_basic_v1.0',
                'name': '基础咖啡包 v1.0',
                'type': 'recipe_pack',
                'version': '1.0.0',
                'description': '包含基本咖啡制作配方',
                'recipes': ['latte', 'americano', 'cappuccino'],
                'size_bytes': 2048,
                'checksum': 'sha256:abc123...',
                'created_at': '2024-01-01T00:00:00Z'
            },
            {
                'id': 'firmware_cm2000_v2.1',
                'name': 'CM-2000固件 v2.1',
                'type': 'firmware',
                'version': '2.1.0',
                'description': 'CM-2000设备固件更新',
                'compatible_models': ['CM-2000'],
                'size_bytes': 1048576,
                'checksum': 'sha256:def456...',
                'created_at': '2024-02-01T00:00:00Z'
            }
        ]
        
        for package in default_packages:
            PackageDictService.create_package(package['id'], package)