"""
配置管理模块
"""
import os
import json
from typing import Dict, Any

class Config:
    """配置类"""
    
    def __init__(self, config_dir: str = None):
        if config_dir is None:
            config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config')
        
        self.config_dir = config_dir
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        # 加载默认配置
        default_path = os.path.join(self.config_dir, 'default.json')
        with open(default_path, 'r', encoding='utf-8') as f:
            default_config = json.load(f)
        
        # 加载设备配置
        device_path = os.path.join(self.config_dir, 'device.json')
        with open(device_path, 'r', encoding='utf-8') as f:
            device_config = json.load(f)
        
        # 合并配置
        config = {**default_config}
        config['device_config'] = device_config
        
        return config
    
    def get(self, key: str, default=None):
        """获取配置项"""
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any):
        """设置配置项"""
        keys = key.split('.')
        config = self._config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
    
    def save_device_config(self):
        """保存设备配置"""
        device_path = os.path.join(self.config_dir, 'device.json')
        with open(device_path, 'w', encoding='utf-8') as f:
            json.dump(self._config.get('device_config', {}), f, indent=2, ensure_ascii=False)
    
    @property
    def device_no(self) -> str:
        """设备编号"""
        return self.get('device_config.device_no', 'UNKNOWN')
    
    @property
    def api_key(self) -> str:
        """API密钥"""
        return self.get('device_config.api_key', '')
    
    @property
    def server_url(self) -> str:
        """服务器URL"""
        return self.get('device_config.server_url', self.get('server.base_url', 'http://localhost:5000'))
    
    @property
    def is_registered(self) -> bool:
        """是否已注册"""
        return self.get('device_config.registered', False)
    
    @property
    def simulation_mode(self) -> bool:
        """是否模拟模式"""
        return self.get('hardware.simulation_mode', True)