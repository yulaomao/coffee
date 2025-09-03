"""
Web工具函数模块
"""
from datetime import datetime
from typing import Dict, Any

def format_datetime(dt: datetime) -> str:
    """格式化日期时间"""
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def format_time(dt: datetime) -> str:
    """格式化时间"""
    return dt.strftime('%H:%M:%S')

def format_date(dt: datetime) -> str:
    """格式化日期"""
    return dt.strftime('%Y-%m-%d')

def safe_get(data: Dict[str, Any], key: str, default=None):
    """安全获取字典值"""
    keys = key.split('.')
    value = data
    
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    
    return value

def format_temperature(temp: float) -> str:
    """格式化温度显示"""
    return f"{temp:.1f}°C"

def format_pressure(pressure: float) -> str:
    """格式化压力显示"""
    return f"{pressure:.1f}bar"

def format_percentage(value: float) -> str:
    """格式化百分比显示"""
    return f"{value:.1f}%"

def format_duration(seconds: float) -> str:
    """格式化时长显示"""
    if seconds < 60:
        return f"{int(seconds)}秒"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        seconds = int(seconds % 60)
        return f"{minutes}分{seconds}秒"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}时{minutes}分"

def get_coffee_icon(coffee_type: str) -> str:
    """获取咖啡类型对应的图标"""
    icon_mapping = {
        'espresso': 'fas fa-coffee',
        'americano': 'fas fa-mug-hot',
        'latte': 'fas fa-coffee',
        'cappuccino': 'fas fa-coffee',
        'macchiato': 'fas fa-coffee'
    }
    return icon_mapping.get(coffee_type, 'fas fa-coffee')

def get_status_color(status: str) -> str:
    """获取状态对应的颜色"""
    color_mapping = {
        'online': 'success',
        'offline': 'danger',
        'idle': 'secondary',
        'brewing': 'primary',
        'error': 'danger',
        'maintenance': 'warning'
    }
    return color_mapping.get(status, 'secondary')