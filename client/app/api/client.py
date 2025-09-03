"""
后台API客户端

负责与管理后台的HTTP API通信
"""
import logging
import requests
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from ..config import Config

logger = logging.getLogger(__name__)

class APIClient:
    """API客户端"""
    
    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        self.session.timeout = config.get('server.timeout', 30)
        self.last_heartbeat = None
        self.authenticated = False
        
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': f'CoffeeClient/{self.config.device_no}'
        }
        
        if self.config.api_key:
            headers['X-API-Key'] = self.config.api_key
            
        return headers
    
    def _make_request(self, method: str, endpoint: str, data: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """发送HTTP请求"""
        url = f"{self.config.server_url}/api/v1/client{endpoint}"
        headers = self._get_headers()
        
        try:
            if method.upper() == 'GET':
                response = self.session.get(url, headers=headers, params=data)
            elif method.upper() == 'POST':
                response = self.session.post(url, headers=headers, json=data)
            elif method.upper() == 'PUT':
                response = self.session.put(url, headers=headers, json=data)
            elif method.upper() == 'DELETE':
                response = self.session.delete(url, headers=headers)
            else:
                raise ValueError(f"不支持的HTTP方法: {method}")
            
            response.raise_for_status()
            
            if response.content:
                return response.json()
            else:
                return {'success': True}
                
        except requests.exceptions.RequestException as e:
            logger.error(f"API请求失败 {method} {endpoint}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"API响应JSON解析失败: {e}")
            return None
    
    def register_device(self, device_info: Dict[str, Any]) -> bool:
        """注册设备"""
        logger.info(f"注册设备: {self.config.device_no}")
        
        data = {
            'device_no': self.config.device_no,
            'device_type': device_info.get('device_type', 'automatic'),
            'location': device_info.get('location', ''),
            'merchant_id': device_info.get('merchant_id')
        }
        
        response = self._make_request('POST', '/register', data)
        if response and response.get('success'):
            # 保存API密钥
            if 'api_key' in response:
                self.config.set('device_config.api_key', response['api_key'])
                self.config.set('device_config.registered', True)
                self.config.save_device_config()
                logger.info("设备注册成功")
                return True
        
        logger.error("设备注册失败")
        return False
    
    def authenticate(self) -> bool:
        """认证设备"""
        if not self.config.api_key:
            logger.error("未设置API密钥，无法认证")
            return False
        
        data = {
            'device_no': self.config.device_no
        }
        
        response = self._make_request('POST', '/auth', data)
        if response and response.get('success'):
            self.authenticated = True
            logger.info("设备认证成功")
            return True
        
        logger.error("设备认证失败")
        return False
    
    def send_heartbeat(self) -> bool:
        """发送心跳"""
        if not self.authenticated:
            if not self.authenticate():
                return False
        
        data = {
            'timestamp': datetime.now().isoformat(),
            'device_no': self.config.device_no
        }
        
        response = self._make_request('POST', '/heartbeat', data)
        if response and response.get('success'):
            self.last_heartbeat = datetime.now()
            return True
        
        return False
    
    def report_status(self, status_data: Dict[str, Any]) -> bool:
        """上报状态数据"""
        if not self.authenticated:
            if not self.authenticate():
                return False
        
        data = {
            'device_no': self.config.device_no,
            'timestamp': datetime.now().isoformat(),
            **status_data
        }
        
        response = self._make_request('POST', '/status', data)
        return response is not None and response.get('success', False)
    
    def report_log(self, level: str, message: str, context: Dict[str, Any] = None) -> bool:
        """上报日志"""
        if not self.authenticated:
            return False  # 日志上报失败不需要认证
        
        data = {
            'device_no': self.config.device_no,
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message,
            'context': context or {}
        }
        
        response = self._make_request('POST', '/logs', data)
        return response is not None and response.get('success', False)
    
    def get_pending_commands(self) -> List[Dict[str, Any]]:
        """获取待执行命令"""
        if not self.authenticated:
            if not self.authenticate():
                return []
        
        response = self._make_request('GET', '/commands')
        if response and response.get('success'):
            return response.get('commands', [])
        
        return []
    
    def report_command_result(self, command_id: str, success: bool, result: Dict[str, Any] = None, error: str = None) -> bool:
        """上报命令执行结果"""
        if not self.authenticated:
            return False
        
        data = {
            'command_id': command_id,
            'device_no': self.config.device_no,
            'success': success,
            'timestamp': datetime.now().isoformat(),
            'result': result or {},
            'error': error
        }
        
        response = self._make_request('POST', '/command-result', data)
        return response is not None and response.get('success', False)
    
    def get_config(self) -> Optional[Dict[str, Any]]:
        """获取设备配置"""
        if not self.authenticated:
            if not self.authenticate():
                return None
        
        response = self._make_request('GET', '/config')
        if response and response.get('success'):
            return response.get('config', {})
        
        return None
    
    def ping(self) -> bool:
        """健康检查"""
        response = self._make_request('GET', '/ping')
        return response is not None and response.get('success', False)
    
    def get_websocket_status(self) -> Dict[str, Any]:
        """获取WebSocket连接状态"""
        response = self._make_request('GET', '/websocket/status')
        if response and response.get('success'):
            return {
                'connected': response.get('websocket_connected', False),
                'stats': response.get('connection_stats', {})
            }
        
        return {'connected': False, 'stats': {}}
    
    def is_healthy(self) -> bool:
        """检查连接健康状态"""
        try:
            return self.ping()
        except Exception as e:
            logger.error(f"健康检查失败: {e}")
            return False
    
    def close(self):
        """关闭客户端"""
        self.session.close()
        self.authenticated = False