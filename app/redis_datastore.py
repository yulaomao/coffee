"""
Redis数据存储服务 - 基于"设备为中心"的数据模型

实现设计文档中的Redis键空间结构：
- 设备作用域前缀：cm:dev:{device_id}:*  
- 全局命名空间前缀：cm:
- 时间使用UNIX epoch秒作为Sorted Set score
"""
from __future__ import annotations
import json
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Union


class RedisDataStore:
    """Redis数据存储服务 - 设备为中心的数据模型"""
    
    PREFIX = "cm:"
    
    def __init__(self):
        self.redis = None
    
    def _get_redis(self):
        """懒加载获取Redis客户端"""
        if self.redis is None:
            try:
                from .extensions import redis_client
                if redis_client is not None:
                    # Test the connection
                    redis_client.ping()
                    self.redis = redis_client
                else:
                    raise Exception("Redis client not initialized")
            except:
                # Fallback to mock Redis for testing
                from .mock_redis import MockRedis
                self.redis = MockRedis()
                print("Using Mock Redis for testing (no Redis server available)")
        return self.redis
    
    # ===================== 辅助方法 =====================
    
    @staticmethod
    def _now_ts() -> int:
        """获取当前UNIX时间戳（秒）"""
        return int(time.time())
    
    @staticmethod
    def _to_json(data: Any) -> str:
        """转换为JSON字符串"""
        return json.dumps(data, ensure_ascii=False) if data is not None else ""
    
    @staticmethod
    def _from_json(data: str) -> Any:
        """从JSON字符串解析"""
        return json.loads(data) if data else None
    
    def _device_key(self, device_id: str, suffix: str = "") -> str:
        """生成设备作用域键名"""
        if suffix:
            return f"{self.PREFIX}dev:{device_id}:{suffix}"
        return f"{self.PREFIX}dev:{device_id}"
    
    def _global_key(self, suffix: str) -> str:
        """生成全局作用域键名"""
        return f"{self.PREFIX}{suffix}"
    
    # ===================== 设备核心信息 =====================
    
    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取设备基础信息"""
        redis = self._get_redis()
        key = self._device_key(device_id)
        data = redis.hgetall(key)
        if not data:
            return None
        
        # 转换JSON字段
        if 'tags_json' in data:
            data['tags'] = self._from_json(data['tags_json'])
        if 'extra_json' in data:
            data['extra'] = self._from_json(data['extra_json'])
        
        return data
    
    def set_device(self, device_id: str, device_data: Dict[str, Any]) -> bool:
        """设置设备基础信息"""
        redis = self._get_redis()
        key = self._device_key(device_id)
        
        # 处理JSON字段
        redis_data = device_data.copy()
        if 'tags' in redis_data:
            redis_data['tags_json'] = self._to_json(redis_data.pop('tags'))
        if 'extra' in redis_data:
            redis_data['extra_json'] = self._to_json(redis_data.pop('extra'))
        
        # 添加时间戳
        redis_data['updated_ts'] = self._now_ts()
        
        return redis.hset(key, mapping=redis_data) >= 0
    
    def update_device_status(self, device_id: str, status: str, **kwargs) -> bool:
        """更新设备状态"""
        redis = self._get_redis()
        key = self._device_key(device_id)
        update_data = {
            'status': status,
            'last_seen_ts': self._now_ts()
        }
        update_data.update(kwargs)
        
        # 同步更新全局状态索引
        old_status = redis.hget(key, 'status')
        if old_status and old_status != status:
            redis.srem(self._global_key(f"idx:device:status:{old_status}"), device_id)
        redis.sadd(self._global_key(f"idx:device:status:{status}"), device_id)
        
        return redis.hset(key, mapping=update_data) >= 0
    
    # ===================== 设备安装点（Location） =====================
    
    def set_device_location(self, device_id: str, location_data: Dict[str, Any]) -> bool:
        """设置设备安装点信息"""
        redis = self._get_redis()
        key = self._device_key(device_id, "loc")
        location_data['updated_ts'] = self._now_ts()
        
        # 记录位置变更历史（可选）
        self._add_location_history(device_id, location_data)
        
        return redis.hset(key, mapping=location_data) >= 0
    
    def _add_location_history(self, device_id: str, location_data: Dict[str, Any]):
        """添加位置变更历史记录"""
        redis = self._get_redis()
        stream_key = self._device_key(device_id, "stream:loc_hist")
        redis.xadd(stream_key, {
            "action": "location_update",
            "data": self._to_json(location_data),
            "ts": self._now_ts()
        })
    
    def get_device_location(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取设备安装点信息"""
        redis = self._get_redis()
        key = self._device_key(device_id, "loc")
        return redis.hgetall(key) or None
    
    # ===================== 料盒与物料（Bins/Materials） =====================
    
    def get_device_bins(self, device_id: str) -> List[Dict[str, Any]]:
        """获取设备所有料盒信息"""
        redis = self._get_redis()
        bins_key = self._device_key(device_id, "bins")
        bin_indexes = redis.smembers(bins_key)
        
        bins = []
        for bin_index in bin_indexes:
            bin_key = self._device_key(device_id, f"bin:{bin_index}")
            bin_data = redis.hgetall(bin_key)
            if bin_data:
                # 转换数值字段
                for field in ['remaining', 'capacity', 'threshold_low_pct']:
                    if field in bin_data:
                        bin_data[field] = float(bin_data[field])
                bins.append(bin_data)
        
        return bins
    
    def set_device_bin(self, device_id: str, bin_index: int, bin_data: Dict[str, Any]) -> bool:
        """设置设备料盒信息"""
        redis = self._get_redis()
        bins_key = self._device_key(device_id, "bins")
        bin_key = self._device_key(device_id, f"bin:{bin_index}")
        
        # 添加到料盒集合
        redis.sadd(bins_key, str(bin_index))
        
        # 设置料盒数据
        bin_data['bin_index'] = bin_index
        bin_data['last_sync_ts'] = self._now_ts()
        
        result = redis.hset(bin_key, mapping=bin_data) >= 0
        
        # 检查是否需要加入低料集合
        self._update_low_material_status(device_id, bin_index, bin_data)
        
        return result
    
    def _update_low_material_status(self, device_id: str, bin_index: int, bin_data: Dict[str, Any]):
        """更新低料状态"""
        redis = self._get_redis()
        low_key = self._device_key(device_id, "bins:low")
        remaining = float(bin_data.get('remaining', 0))
        capacity = float(bin_data.get('capacity', 100))
        threshold = float(bin_data.get('threshold_low_pct', 10))
        
        if remaining <= (capacity * threshold / 100):
            redis.sadd(low_key, str(bin_index))
        else:
            redis.srem(low_key, str(bin_index))
    
    def get_device_low_bins(self, device_id: str) -> List[str]:
        """获取设备低料料盒列表"""
        redis = self._get_redis()
        low_key = self._device_key(device_id, "bins:low")
        return list(redis.smembers(low_key))
    
    # ===================== 订单（Orders） =====================
    
    def get_device_order(self, device_id: str, order_id: str) -> Optional[Dict[str, Any]]:
        """获取设备订单信息"""
        redis = self._get_redis()
        key = self._device_key(device_id, f"order:{order_id}")
        order_data = redis.hgetall(key)
        if not order_data:
            return None
        
        # 转换JSON字段
        if 'items_json' in order_data:
            order_data['items'] = self._from_json(order_data['items_json'])
        if 'meta_json' in order_data:
            order_data['meta'] = self._from_json(order_data['meta_json'])
        
        return order_data
    
    def create_device_order(self, device_id: str, order_id: str, order_data: Dict[str, Any]) -> bool:
        """创建设备订单（幂等）"""
        redis = self._get_redis()
        order_key = self._device_key(device_id, f"order:{order_id}")
        orders_index_key = self._device_key(device_id, "orders:by_ts")
        
        # 处理JSON字段
        redis_data = order_data.copy()
        redis_data['order_id'] = order_id
        redis_data['device_id'] = device_id
        
        if 'items' in redis_data:
            redis_data['items_json'] = self._to_json(redis_data.pop('items'))
        if 'meta' in redis_data:
            redis_data['meta_json'] = self._to_json(redis_data.pop('meta'))
        
        server_ts = self._now_ts()
        redis_data['server_ts'] = server_ts
        
        # 存储订单数据
        pipe = redis.pipeline()
        pipe.hset(order_key, mapping=redis_data)
        
        # 添加时间索引
        pipe.zadd(orders_index_key, {order_id: server_ts})
        
        # 更新日聚合数据
        self._update_daily_order_stats(device_id, order_data, server_ts, pipe)
        
        # 添加全局索引（可选）
        day_key = datetime.fromtimestamp(server_ts).strftime('%Y%m%d')
        pipe.zadd(self._global_key(f"idx:order:day:{day_key}"), {f"{device_id}|{order_id}": server_ts})
        
        return all(pipe.execute())
    
    def _update_daily_order_stats(self, device_id: str, order_data: Dict[str, Any], server_ts: int, pipe):
        """更新日级订单聚合数据"""
        day_str = datetime.fromtimestamp(server_ts).strftime('%Y%m%d')
        count_key = self._device_key(device_id, f"agg:orders:day:{day_str}:count")
        revenue_key = self._device_key(device_id, f"agg:orders:day:{day_str}:revenue_cents")
        
        # 订单数量+1
        pipe.incr(count_key)
        
        # 营收累加（转换为分）
        total_price = order_data.get('total_price', 0)
        revenue_cents = int(float(total_price) * 100)
        pipe.incrby(revenue_key, revenue_cents)
    
    def get_device_orders_by_timerange(self, device_id: str, start_ts: int, end_ts: int, 
                                     limit: int = 100) -> List[Dict[str, Any]]:
        """按时间范围获取设备订单"""
        redis = self._get_redis()
        index_key = self._device_key(device_id, "orders:by_ts")
        order_ids = redis.zrangebyscore(index_key, start_ts, end_ts, withscores=False, 
                                           start=0, num=limit)
        
        orders = []
        for order_id in order_ids:
            order_data = self.get_device_order(device_id, order_id)
            if order_data:
                orders.append(order_data)
        
        return orders
    
    def get_device_daily_stats(self, device_id: str, day_str: str) -> Dict[str, Any]:
        """获取设备日统计数据"""
        redis = self._get_redis()
        count_key = self._device_key(device_id, f"agg:orders:day:{day_str}:count")
        revenue_key = self._device_key(device_id, f"agg:orders:day:{day_str}:revenue_cents")
        
        count = redis.get(count_key) or "0"
        revenue_cents = redis.get(revenue_key) or "0"
        
        return {
            "day": day_str,
            "orders_count": int(count),
            "revenue_cents": int(revenue_cents),
            "revenue": float(revenue_cents) / 100
        }
    
    # ===================== 告警（Alarms） =====================
    
    def get_device_alarm(self, device_id: str, alarm_id: str) -> Optional[Dict[str, Any]]:
        """获取设备告警信息"""
        redis = self._get_redis()
        key = self._device_key(device_id, f"alarm:{alarm_id}")
        alarm_data = redis.hgetall(key)
        if not alarm_data:
            return None
        
        if 'context_json' in alarm_data:
            alarm_data['context'] = self._from_json(alarm_data['context_json'])
        
        return alarm_data
    
    def create_device_alarm(self, device_id: str, alarm_id: str, alarm_data: Dict[str, Any]) -> bool:
        """创建设备告警"""
        redis = self._get_redis()
        alarm_key = self._device_key(device_id, f"alarm:{alarm_id}")
        alarms_index_key = self._device_key(device_id, "alarms:by_ts")
        
        redis_data = alarm_data.copy()
        redis_data['id'] = alarm_id
        redis_data['device_id'] = device_id
        
        if 'context' in redis_data:
            redis_data['context_json'] = self._to_json(redis_data.pop('context'))
        
        created_ts = self._now_ts()
        redis_data['created_ts'] = created_ts
        redis_data['updated_ts'] = created_ts
        
        status = redis_data.get('status', 'open')
        
        pipe = redis.pipeline()
        
        # 存储告警数据
        pipe.hset(alarm_key, mapping=redis_data)
        
        # 添加时间索引
        pipe.zadd(alarms_index_key, {alarm_id: created_ts})
        
        # 添加状态索引
        status_key = self._device_key(device_id, f"alarms:status:{status}")
        pipe.sadd(status_key, alarm_id)
        
        # 添加全局索引（可选）
        alarm_type = alarm_data.get('type', 'unknown')
        pipe.sadd(self._global_key(f"idx:alarm:type:{alarm_type}"), f"{device_id}|{alarm_id}")
        
        return all(pipe.execute())
    
    def update_device_alarm_status(self, device_id: str, alarm_id: str, new_status: str) -> bool:
        """更新设备告警状态"""
        alarm_key = self._device_key(device_id, f"alarm:{alarm_id}")
        
        # 获取旧状态
        old_status = redis.hget(alarm_key, 'status')
        
        pipe = redis.pipeline()
        
        # 更新告警状态
        pipe.hset(alarm_key, mapping={
            'status': new_status,
            'updated_ts': self._now_ts()
        })
        
        # 更新状态索引
        if old_status and old_status != new_status:
            old_status_key = self._device_key(device_id, f"alarms:status:{old_status}")
            pipe.srem(old_status_key, alarm_id)
        
        new_status_key = self._device_key(device_id, f"alarms:status:{new_status}")
        pipe.sadd(new_status_key, alarm_id)
        
        return all(pipe.execute())
    
    def get_device_alarms_by_status(self, device_id: str, status: str) -> List[str]:
        """按状态获取设备告警ID列表"""
        redis = self._get_redis()
        status_key = self._device_key(device_id, f"alarms:status:{status}")
        return list(redis.smembers(status_key))
    
    # ===================== 远程命令（RemoteCommand） =====================
    
    def get_device_command(self, device_id: str, command_id: str) -> Optional[Dict[str, Any]]:
        """获取设备命令信息"""
        redis = self._get_redis()
        key = self._device_key(device_id, f"cmd:{command_id}")
        cmd_data = redis.hgetall(key)
        if not cmd_data:
            return None
        
        # 转换JSON字段
        for json_field in ['payload_json', 'result_payload_json']:
            if json_field in cmd_data:
                field_name = json_field.replace('_json', '')
                cmd_data[field_name] = self._from_json(cmd_data[json_field])
        
        return cmd_data
    
    def create_device_command(self, device_id: str, command_id: str, command_data: Dict[str, Any]) -> bool:
        """创建设备命令"""
        redis = self._get_redis()
        cmd_key = self._device_key(device_id, f"cmd:{command_id}")
        pending_queue_key = self._device_key(device_id, "q:cmd:pending")
        cmds_index_key = self._device_key(device_id, "cmds:by_ts")
        
        redis_data = command_data.copy()
        redis_data['command_id'] = command_id
        redis_data['device_id'] = device_id
        redis_data['status'] = redis_data.get('status', 'pending')
        
        # 处理JSON字段
        if 'payload' in redis_data:
            redis_data['payload_json'] = self._to_json(redis_data.pop('payload'))
        
        issued_ts = self._now_ts()
        redis_data['issued_ts'] = issued_ts
        
        pipe = redis.pipeline()
        
        # 存储命令数据
        pipe.hset(cmd_key, mapping=redis_data)
        
        # 加入待执行队列
        pipe.lpush(pending_queue_key, command_id)
        
        # 时间索引（可选）
        pipe.zadd(cmds_index_key, {command_id: issued_ts})
        
        return all(pipe.execute())
    
    def pop_device_pending_command(self, device_id: str) -> Optional[str]:
        """从设备待执行队列中弹出命令"""
        redis = self._get_redis()
        pending_queue_key = self._device_key(device_id, "q:cmd:pending")
        inflight_set_key = self._device_key(device_id, "cmd:inflight")
        
        command_id = redis.rpop(pending_queue_key)
        if command_id:
            # 移至执行中集合
            redis.sadd(inflight_set_key, command_id)
        
        return command_id
    
    def complete_device_command(self, device_id: str, command_id: str, status: str, 
                               result_payload: Optional[Dict[str, Any]] = None) -> bool:
        """完成设备命令执行"""
        redis = self._get_redis()
        cmd_key = self._device_key(device_id, f"cmd:{command_id}")
        inflight_set_key = self._device_key(device_id, "cmd:inflight")
        
        update_data = {
            'status': status,
            'result_ts': self._now_ts()
        }
        
        if result_payload is not None:
            update_data['result_payload_json'] = self._to_json(result_payload)
        
        pipe = redis.pipeline()
        
        # 更新命令状态
        pipe.hset(cmd_key, mapping=update_data)
        
        # 从执行中集合移除
        pipe.srem(inflight_set_key, command_id)
        
        return all(pipe.execute())
    
    # ===================== 全局字典数据 =====================
    
    def get_material_dict(self, material_code: str) -> Optional[Dict[str, Any]]:
        """获取物料字典信息"""
        redis = self._get_redis()
        key = self._global_key(f"dict:material:{material_code}")
        return redis.hgetall(key) or None
    
    def set_material_dict(self, material_code: str, material_data: Dict[str, Any]) -> bool:
        """设置物料字典信息"""
        redis = self._get_redis()
        key = self._global_key(f"dict:material:{material_code}")
        all_key = self._global_key("dict:material:all")
        
        pipe = redis.pipeline()
        pipe.hset(key, mapping=material_data)
        pipe.sadd(all_key, material_code)
        
        return all(pipe.execute())
    
    def get_all_materials(self) -> List[str]:
        """获取所有物料代码列表"""
        redis = self._get_redis()
        all_key = self._global_key("dict:material:all")
        return list(redis.smembers(all_key))
    
    # ===================== 设备配方包状态 =====================
    
    def get_device_installed_packages(self, device_id: str) -> List[str]:
        """获取设备已安装包列表"""
        redis = self._get_redis()
        key = self._device_key(device_id, "packages:installed")
        return list(redis.smembers(key))
    
    def install_device_package(self, device_id: str, package_id: str, install_meta: Dict[str, Any]) -> bool:
        """安装设备包"""
        redis = self._get_redis()
        installed_key = self._device_key(device_id, "packages:installed")
        package_key = self._device_key(device_id, f"package:{package_id}")
        
        install_meta['installed_ts'] = self._now_ts()
        
        pipe = redis.pipeline()
        pipe.sadd(installed_key, package_id)
        pipe.hset(package_key, mapping=install_meta)
        
        return all(pipe.execute())
    
    def get_device_active_recipes(self, device_id: str) -> List[str]:
        """获取设备激活配方列表"""
        redis = self._get_redis()
        key = self._device_key(device_id, "recipes:active")
        return list(redis.smembers(key))
    
    def activate_device_recipe(self, device_id: str, recipe_id: str) -> bool:
        """激活设备配方"""
        redis = self._get_redis()
        key = self._device_key(device_id, "recipes:active")
        return redis.sadd(key, recipe_id) >= 0
    
    def deactivate_device_recipe(self, device_id: str, recipe_id: str) -> bool:
        """停用设备配方"""
        redis = self._get_redis()
        key = self._device_key(device_id, "recipes:active")
        return redis.srem(key, recipe_id) >= 0
    
    # ===================== 审计日志 =====================
    
    def add_device_audit_log(self, device_id: str, action: str, target: str, 
                           summary: str, payload: Optional[Dict[str, Any]] = None):
        """添加设备审计日志"""
        redis = self._get_redis()
        stream_key = self._device_key(device_id, "stream:audit")
        log_data = {
            "action": action,
            "target": target,
            "summary": summary,
            "ts": self._now_ts()
        }
        if payload:
            log_data["payload"] = self._to_json(payload)
        
        redis.xadd(stream_key, log_data)
    
    def get_device_recent_logs(self, device_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """获取设备最近操作日志"""
        redis = self._get_redis()
        list_key = self._device_key(device_id, "oplog:recent")
        logs = redis.lrange(list_key, 0, limit - 1)
        return [self._from_json(log) for log in logs]
    
    def add_device_recent_log(self, device_id: str, log_data: Dict[str, Any]):
        """添加设备最近操作日志（有限列表）"""
        redis = self._get_redis()
        list_key = self._device_key(device_id, "oplog:recent")
        pipe = redis.pipeline()
        pipe.lpush(list_key, self._to_json(log_data))
        pipe.ltrim(list_key, 0, 999)  # 保留最近1000条
        pipe.execute()

# 全局实例
datastore = RedisDataStore()