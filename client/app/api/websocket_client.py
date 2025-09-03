"""
WebSocket客户端

负责与管理后台的实时通信
"""
import logging
import json
from datetime import datetime
from typing import Dict, Any, Callable, Optional
from threading import Thread, Event
import socketio
from ..config import Config

logger = logging.getLogger(__name__)

class WebSocketClient:
    """WebSocket客户端"""
    
    def __init__(self, config: Config):
        self.config = config
        self.sio = socketio.Client(reconnection=True, reconnection_attempts=5, reconnection_delay=5)
        self.connected = False
        self.authenticated = False
        self.event_handlers = {}
        self.stop_event = Event()
        
        # 注册内置事件处理器
        self._register_handlers()
    
    def _register_handlers(self):
        """注册事件处理器"""
        @self.sio.event
        def connect():
            logger.info("WebSocket连接已建立")
            self.connected = True
            self._authenticate()
        
        @self.sio.event
        def disconnect():
            logger.info("WebSocket连接已断开")
            self.connected = False
            self.authenticated = False
        
        @self.sio.event
        def connect_error(data):
            logger.error(f"WebSocket连接错误: {data}")
            self.connected = False
            self.authenticated = False
        
        @self.sio.event
        def auth_success(data):
            logger.info("WebSocket认证成功")
            self.authenticated = True
            # 触发自定义事件
            self._trigger_event('authenticated', data)
        
        @self.sio.event
        def auth_error(data):
            logger.error(f"WebSocket认证失败: {data}")
            self.authenticated = False
            # 触发自定义事件
            self._trigger_event('auth_error', data)
        
        @self.sio.event
        def command(data):
            """接收远程命令"""
            logger.info(f"收到远程命令: {data}")
            self._trigger_event('command_received', data)
        
        @self.sio.event
        def config_update(data):
            """配置更新"""
            logger.info(f"收到配置更新: {data}")
            self._trigger_event('config_updated', data)
        
        @self.sio.event
        def error(data):
            """错误事件"""
            logger.error(f"WebSocket错误: {data}")
            self._trigger_event('error', data)
    
    def _authenticate(self):
        """WebSocket认证"""
        if not self.config.api_key:
            logger.error("未设置API密钥，无法进行WebSocket认证")
            return
        
        auth_data = {
            'api_key': self.config.api_key,
            'device_no': self.config.device_no,
            'device_type': 'client'
        }
        
        logger.info("发送WebSocket认证请求")
        self.sio.emit('device_auth', auth_data)
    
    def _trigger_event(self, event_name: str, data: Dict[str, Any]):
        """触发自定义事件"""
        if event_name in self.event_handlers:
            for handler in self.event_handlers[event_name]:
                try:
                    handler(data)
                except Exception as e:
                    logger.error(f"事件处理器错误 {event_name}: {e}")
    
    def on(self, event: str, handler: Callable[[Dict[str, Any]], None]):
        """注册事件处理器"""
        if event not in self.event_handlers:
            self.event_handlers[event] = []
        self.event_handlers[event].append(handler)
    
    def off(self, event: str, handler: Callable = None):
        """移除事件处理器"""
        if event in self.event_handlers:
            if handler:
                if handler in self.event_handlers[event]:
                    self.event_handlers[event].remove(handler)
            else:
                self.event_handlers[event] = []
    
    def connect_async(self) -> bool:
        """异步连接WebSocket"""
        try:
            websocket_url = self.config.get('server.websocket_url', self.config.server_url)
            logger.info(f"连接WebSocket服务器: {websocket_url}")
            
            # 在新线程中连接
            def connect_thread():
                try:
                    self.sio.connect(websocket_url, wait=True, wait_timeout=10)
                except Exception as e:
                    logger.error(f"WebSocket连接线程错误: {e}")
            
            thread = Thread(target=connect_thread, daemon=True)
            thread.start()
            return True
            
        except Exception as e:
            logger.error(f"WebSocket连接失败: {e}")
            return False
    
    def disconnect(self):
        """断开WebSocket连接"""
        try:
            if self.sio.connected:
                self.sio.disconnect()
            self.connected = False
            self.authenticated = False
            logger.info("WebSocket已断开")
        except Exception as e:
            logger.error(f"WebSocket断开错误: {e}")
    
    def send_status(self, status_data: Dict[str, Any]) -> bool:
        """发送状态数据"""
        if not self.authenticated:
            logger.warning("WebSocket未认证，无法发送状态")
            return False
        
        try:
            data = {
                'device_no': self.config.device_no,
                'timestamp': datetime.now().isoformat(),
                **status_data
            }
            
            self.sio.emit('device_status', data)
            logger.debug(f"发送设备状态: {data}")
            return True
            
        except Exception as e:
            logger.error(f"发送设备状态失败: {e}")
            return False
    
    def send_log(self, level: str, message: str, context: Dict[str, Any] = None) -> bool:
        """发送日志"""
        if not self.authenticated:
            return False
        
        try:
            data = {
                'device_no': self.config.device_no,
                'timestamp': datetime.now().isoformat(),
                'level': level,
                'message': message,
                'context': context or {}
            }
            
            self.sio.emit('device_log', data)
            logger.debug(f"发送设备日志: {message}")
            return True
            
        except Exception as e:
            logger.error(f"发送设备日志失败: {e}")
            return False
    
    def send_command_result(self, command_id: str, success: bool, result: Dict[str, Any] = None, error: str = None) -> bool:
        """发送命令执行结果"""
        if not self.authenticated:
            logger.warning("WebSocket未认证，无法发送命令结果")
            return False
        
        try:
            data = {
                'command_id': command_id,
                'device_no': self.config.device_no,
                'timestamp': datetime.now().isoformat(),
                'success': success,
                'result': result or {},
                'error': error
            }
            
            self.sio.emit('device_command_result', data)
            logger.info(f"发送命令结果: {command_id}, 成功: {success}")
            return True
            
        except Exception as e:
            logger.error(f"发送命令结果失败: {e}")
            return False
    
    def send_heartbeat(self) -> bool:
        """发送心跳"""
        if not self.authenticated:
            return False
        
        try:
            data = {
                'device_no': self.config.device_no,
                'timestamp': datetime.now().isoformat()
            }
            
            self.sio.emit('device_heartbeat', data)
            logger.debug("发送WebSocket心跳")
            return True
            
        except Exception as e:
            logger.error(f"发送心跳失败: {e}")
            return False
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self.connected and self.sio.connected
    
    def is_authenticated(self) -> bool:
        """检查认证状态"""
        return self.authenticated
    
    def wait_for_disconnect(self):
        """等待断开连接"""
        try:
            self.sio.wait()
        except Exception as e:
            logger.error(f"等待断开连接时出错: {e}")