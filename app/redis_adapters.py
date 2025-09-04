"""
Redis适配器层 - 提供与现有SQLAlchemy接口兼容的Redis操作

渐进式迁移策略：保持现有API接口，逐步将底层实现替换为Redis
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from .redis_datastore import datastore
from .models import Device as DeviceModel  # 保留模型定义以获取字段信息


class DeviceAdapter:
    """设备Redis适配器"""
    
    @staticmethod
    def get_by_id(device_id: int) -> Optional[Dict[str, Any]]:
        """根据ID获取设备信息"""
        return datastore.get_device(str(device_id))
    
    @staticmethod
    def get_by_device_no(device_no: str) -> Optional[Dict[str, Any]]:
        """根据设备编号获取设备信息（需要通过索引查找）"""
        # TODO: 需要建立 device_no -> device_id 的索引
        # 暂时先遍历查找
        devices = DeviceAdapter.get_all()
        for device in devices:
            if device.get('device_no') == device_no:
                return device
        return None
    
    @staticmethod
    def get_all(merchant_id: Optional[int] = None, status: Optional[str] = None, 
               limit: int = 100) -> List[Dict[str, Any]]:
        """获取设备列表"""
        devices = []
        
        if status:
            # 通过状态索引查找
            redis = datastore._get_redis()
            device_ids = redis.smembers(f"cm:idx:device:status:{status}")
        else:
            # 获取所有设备ID（需要全局设备索引）
            redis = datastore._get_redis()
            device_ids = redis.smembers("cm:idx:device:all")
        
        for device_id in device_ids:
            device = datastore.get_device(device_id)
            if device:
                if merchant_id and device.get('merchant_id') != str(merchant_id):
                    continue
                devices.append(device)
                if len(devices) >= limit:
                    break
        
        return devices
    
    @staticmethod
    def create(device_data: Dict[str, Any]) -> str:
        """创建设备，返回device_id"""
        device_id = str(uuid.uuid4())
        
        # 设置默认值
        device_data.update({
            'device_id': device_id,
            'status': device_data.get('status', 'offline'),
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        })
        
        # 存储设备
        datastore.set_device(device_id, device_data)
        
        # 建立索引
        redis = datastore._get_redis()
        redis.sadd("cm:idx:device:all", device_id)
        redis.sadd(f"cm:idx:device:status:{device_data['status']}", device_id)
        
        if 'merchant_id' in device_data:
            redis.sadd(f"cm:idx:merchant:{device_data['merchant_id']}:devices", device_id)
        
        if 'device_no' in device_data:
            redis.set(f"cm:idx:device_no:{device_data['device_no']}", device_id)
        
        return device_id
    
    @staticmethod
    def update(device_id: str, update_data: Dict[str, Any]) -> bool:
        """更新设备信息"""
        current_device = datastore.get_device(device_id)
        if not current_device:
            return False
        
        current_device.update(update_data)
        current_device['updated_at'] = datetime.utcnow().isoformat()
        
        return datastore.set_device(device_id, current_device)
    
    @staticmethod
    def update_status(device_id: str, status: str, **kwargs) -> bool:
        """更新设备状态"""
        return datastore.update_device_status(device_id, status, **kwargs)
    
    @staticmethod
    def get_location(device_id: str) -> Optional[Dict[str, Any]]:
        """获取设备位置信息"""
        return datastore.get_device_location(device_id)
    
    @staticmethod
    def set_location(device_id: str, location_data: Dict[str, Any]) -> bool:
        """设置设备位置信息"""
        return datastore.set_device_location(device_id, location_data)


class OrderAdapter:
    """订单Redis适配器"""
    
    @staticmethod
    def get_by_device(device_id: str, start_time: Optional[datetime] = None,
                     end_time: Optional[datetime] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """获取设备订单列表"""
        if start_time and end_time:
            start_ts = int(start_time.timestamp())
            end_ts = int(end_time.timestamp())
            return datastore.get_device_orders_by_timerange(str(device_id), start_ts, end_ts, limit)
        else:
            # 获取最近订单
            import time
            now_ts = int(time.time())
            start_ts = now_ts - (30 * 24 * 3600)  # 最近30天
            return datastore.get_device_orders_by_timerange(str(device_id), start_ts, now_ts, limit)
    
    @staticmethod
    def create(device_id: str, order_data: Dict[str, Any]) -> str:
        """创建订单"""
        order_id = order_data.get('order_id') or str(uuid.uuid4())
        
        # 确保必要字段
        order_data.update({
            'order_id': order_id,
            'device_id': str(device_id),
            'created_at': datetime.utcnow().isoformat()
        })
        
        datastore.create_device_order(str(device_id), order_id, order_data)
        return order_id
    
    @staticmethod
    def get_daily_stats(device_id: str, date_str: str) -> Dict[str, Any]:
        """获取设备日统计"""
        day_str = date_str.replace('-', '')  # 转换为YYYYMMDD格式
        return datastore.get_device_daily_stats(str(device_id), day_str)


class MaterialAdapter:
    """物料Redis适配器"""
    
    @staticmethod
    def get_device_bins(device_id: str) -> List[Dict[str, Any]]:
        """获取设备料盒列表"""
        return datastore.get_device_bins(str(device_id))
    
    @staticmethod
    def set_device_bin(device_id: str, bin_index: int, bin_data: Dict[str, Any]) -> bool:
        """设置设备料盒信息"""
        return datastore.set_device_bin(str(device_id), bin_index, bin_data)
    
    @staticmethod
    def get_device_low_bins(device_id: str) -> List[str]:
        """获取设备低料料盒"""
        return datastore.get_device_low_bins(str(device_id))
    
    @staticmethod
    def get_material_dict(material_code: str) -> Optional[Dict[str, Any]]:
        """获取物料字典信息"""
        return datastore.get_material_dict(material_code)
    
    @staticmethod
    def get_all_materials() -> List[str]:
        """获取所有物料代码"""
        return datastore.get_all_materials()


class AlarmAdapter:
    """告警Redis适配器"""
    
    @staticmethod
    def create(device_id: str, alarm_data: Dict[str, Any]) -> str:
        """创建告警"""
        alarm_id = str(uuid.uuid4())
        alarm_data['created_at'] = datetime.utcnow().isoformat()
        
        datastore.create_device_alarm(str(device_id), alarm_id, alarm_data)
        return alarm_id
    
    @staticmethod
    def get_by_device_and_status(device_id: str, status: str) -> List[Dict[str, Any]]:
        """获取设备指定状态的告警"""
        alarm_ids = datastore.get_device_alarms_by_status(str(device_id), status)
        alarms = []
        
        for alarm_id in alarm_ids:
            alarm = datastore.get_device_alarm(str(device_id), alarm_id)
            if alarm:
                alarms.append(alarm)
        
        return alarms
    
    @staticmethod
    def update_status(device_id: str, alarm_id: str, new_status: str) -> bool:
        """更新告警状态"""
        return datastore.update_device_alarm_status(str(device_id), alarm_id, new_status)


class CommandAdapter:
    """命令Redis适配器"""
    
    @staticmethod
    def create(device_id: str, command_data: Dict[str, Any]) -> str:
        """创建远程命令"""
        command_id = str(uuid.uuid4())
        command_data['created_at'] = datetime.utcnow().isoformat()
        
        datastore.create_device_command(str(device_id), command_id, command_data)
        return command_id
    
    @staticmethod
    def get_pending_command(device_id: str) -> Optional[Dict[str, Any]]:
        """获取待执行命令"""
        command_id = datastore.pop_device_pending_command(str(device_id))
        if command_id:
            return datastore.get_device_command(str(device_id), command_id)
        return None
    
    @staticmethod
    def complete_command(device_id: str, command_id: str, status: str,
                        result: Optional[Dict[str, Any]] = None) -> bool:
        """完成命令执行"""
        return datastore.complete_device_command(str(device_id), command_id, status, result)


# 导出适配器实例
device_adapter = DeviceAdapter()
order_adapter = OrderAdapter()
material_adapter = MaterialAdapter()
alarm_adapter = AlarmAdapter()
command_adapter = CommandAdapter()