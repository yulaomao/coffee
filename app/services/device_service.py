"""
设备服务层 - 使用Redis数据存储的设备管理功能

提供与原有API兼容的设备管理服务，底层使用Redis存储
"""
from __future__ import annotations
import uuid
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Union
from ..redis_adapters import device_adapter, order_adapter, material_adapter, alarm_adapter, command_adapter


class DeviceService:
    """设备服务 - Redis存储"""
    
    @staticmethod
    def list_devices(merchant_id: Optional[int] = None, status: Optional[str] = None,
                    search: Optional[str] = None, page: int = 1, per_page: int = 20) -> Dict[str, Any]:
        """获取设备列表"""
        # 获取基础设备列表
        devices = device_adapter.get_all(merchant_id=merchant_id, status=status, limit=per_page * 2)
        
        # 应用搜索过滤
        if search:
            search_lower = search.lower()
            devices = [d for d in devices if 
                      search_lower in (d.get('device_no', '') or '').lower() or
                      search_lower in (d.get('model', '') or '').lower()]
        
        # 分页
        total = len(devices)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_devices = devices[start_idx:end_idx]
        
        # 增强设备信息
        result_items = []
        today_str = datetime.utcnow().strftime('%Y-%m-%d')
        
        for device in page_devices:
            device_id = device.get('device_id')
            
            # 获取今日销量
            today_sales = 0
            if device_id:
                daily_stats = order_adapter.get_daily_stats(device_id, today_str)
                today_sales = daily_stats.get('orders_count', 0)
            
            result_items.append({
                "device_no": device.get('device_no'),
                "alias": device.get('alias'),
                "model": device.get('model'),
                "status": device.get('status'),
                "last_seen": device.get('last_seen_ts'),
                "location_lat": device.get('location_lat'),
                "location_lng": device.get('location_lng'), 
                "merchant_name": device.get('merchant_name'),  # TODO: 需要从merchant服务获取
                "address": device.get('address'),
                "scene": device.get('scene'),
                "customer_code": device.get('customer_code'),
                "custom_fields": device.get('custom_fields', {}),
                "today_sales": today_sales,
                "id": device_id
            })
        
        return {
            "items": result_items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page
        }
    
    @staticmethod
    def get_device_by_no(device_no: str) -> Optional[Dict[str, Any]]:
        """根据设备编号获取设备"""
        return device_adapter.get_by_device_no(device_no)
    
    @staticmethod
    def get_device_by_id(device_id: str) -> Optional[Dict[str, Any]]:
        """根据设备ID获取设备"""
        return device_adapter.get_by_id(device_id)
    
    @staticmethod
    def update_device(device_id: str, update_data: Dict[str, Any]) -> bool:
        """更新设备信息"""
        return device_adapter.update(device_id, update_data)
    
    @staticmethod
    def get_device_materials(device_id: str) -> List[Dict[str, Any]]:
        """获取设备物料信息"""
        return material_adapter.get_device_bins(device_id)
    
    @staticmethod
    def get_device_orders(device_id: str, start_date: Optional[date] = None, 
                         end_date: Optional[date] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """获取设备订单"""
        start_time = None
        end_time = None
        
        if start_date:
            start_time = datetime.combine(start_date, datetime.min.time())
        if end_date:
            end_time = datetime.combine(end_date, datetime.max.time())
        
        return order_adapter.get_by_device(device_id, start_time, end_time, limit)
    
    @staticmethod
    def get_device_daily_stats(device_id: str, date_str: str) -> Dict[str, Any]:
        """获取设备日统计"""
        return order_adapter.get_daily_stats(device_id, date_str)
    
    @staticmethod
    def create_device_command(device_id: str, command_type: str, payload: Dict[str, Any],
                            user_id: Optional[int] = None) -> str:
        """创建设备命令"""
        command_data = {
            'type': command_type,
            'payload': payload,
            'status': 'pending',
            'created_by': user_id
        }
        return command_adapter.create(device_id, command_data)
    
    @staticmethod
    def get_device_location(device_id: str) -> Optional[Dict[str, Any]]:
        """获取设备位置信息"""
        return device_adapter.get_location(device_id)
    
    @staticmethod
    def update_device_location(device_id: str, location_data: Dict[str, Any]) -> bool:
        """更新设备位置信息"""
        return device_adapter.set_location(device_id, location_data)


class DeviceStatsService:
    """设备统计服务"""
    
    @staticmethod
    def get_device_charts_data(device_id: str, chart_type: str = "series", 
                              month: Optional[str] = None) -> Dict[str, Any]:
        """获取设备图表数据"""
        if chart_type == "series":
            return DeviceStatsService._get_series_data(device_id, month)
        elif chart_type == "category":
            return DeviceStatsService._get_category_data(device_id, month)
        else:
            return {}
    
    @staticmethod
    def _get_series_data(device_id: str, month: Optional[str] = None) -> Dict[str, Any]:
        """获取时间序列数据"""
        # 默认最近30天
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=29)
        
        if month:
            try:
                year, month_num = month.split('-')
                start_date = date(int(year), int(month_num), 1)
                if int(month_num) == 12:
                    end_date = date(int(year) + 1, 1, 1) - timedelta(days=1)
                else:
                    end_date = date(int(year), int(month_num) + 1, 1) - timedelta(days=1)
            except:
                pass
        
        # 生成日期范围内的统计数据
        dates = []
        sales_counts = []
        revenues = []
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            daily_stats = order_adapter.get_daily_stats(device_id, date_str)
            
            dates.append(date_str)
            sales_counts.append(daily_stats.get('orders_count', 0))
            revenues.append(daily_stats.get('revenue', 0))
            
            current_date += timedelta(days=1)
        
        return {
            "dates": dates,
            "sales": sales_counts,
            "revenue": revenues
        }
    
    @staticmethod
    def _get_category_data(device_id: str, month: Optional[str] = None) -> Dict[str, Any]:
        """获取分类统计数据"""
        # 获取最近订单并按产品分类统计
        orders = order_adapter.get_by_device(device_id, limit=1000)
        
        category_stats = {}
        for order in orders:
            product_name = order.get('product_name', '未知产品')
            if product_name not in category_stats:
                category_stats[product_name] = {
                    'count': 0,
                    'revenue': 0
                }
            
            category_stats[product_name]['count'] += 1
            category_stats[product_name]['revenue'] += float(order.get('total_price', 0))
        
        categories = list(category_stats.keys())
        counts = [category_stats[cat]['count'] for cat in categories]
        revenues = [category_stats[cat]['revenue'] for cat in categories]
        
        return {
            "categories": categories,
            "counts": counts,
            "revenues": revenues
        }