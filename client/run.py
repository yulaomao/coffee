#!/usr/bin/env python3
"""
咖啡机客户端主启动脚本
"""
import os
import sys
import logging
import signal
import threading
import time
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, socketio
from app.config import Config
from app.core.hardware import create_hardware_interface
from app.core.coffee_maker import create_coffee_maker
from app.api.client import APIClient
from app.api.websocket_client import WebSocketClient
from app.web.routes import set_components

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CoffeeClientApp:
    """咖啡机客户端应用"""
    
    def __init__(self):
        self.config = Config()
        self.app = None
        self.hardware = None
        self.coffee_maker = None
        self.api_client = None
        self.websocket_client = None
        self.running = False
        
        # 后台任务
        self.status_thread = None
        self.heartbeat_thread = None
        self.command_thread = None
        
    def initialize(self):
        """初始化应用"""
        logger.info("初始化咖啡机客户端...")
        
        try:
            # 创建Flask应用
            self.app = create_app()
            self.app.config['CLIENT_CONFIG'] = self.config._config
            
            # 初始化硬件接口
            hardware_config = self.config.get('hardware', {})
            self.hardware = create_hardware_interface(hardware_config)
            
            if not self.hardware.initialize():
                raise RuntimeError("硬件初始化失败")
            
            # 创建咖啡机控制器
            self.coffee_maker = create_coffee_maker(self.hardware, self.config._config)
            
            if not self.coffee_maker.initialize():
                raise RuntimeError("咖啡机控制器初始化失败")
            
            # 创建API客户端
            self.api_client = APIClient(self.config)
            
            # 创建WebSocket客户端
            self.websocket_client = WebSocketClient(self.config)
            
            # 设置组件引用
            set_components(self.coffee_maker, self.hardware, self.api_client, self.websocket_client)
            
            # 注册事件处理器
            self._register_event_handlers()
            
            logger.info("咖啡机客户端初始化完成")
            return True
            
        except Exception as e:
            logger.error(f"初始化失败: {e}")
            return False
    
    def _register_event_handlers(self):
        """注册事件处理器"""
        # 咖啡机状态变化回调
        self.coffee_maker.add_status_callback(self._on_coffee_status_change)
        
        # WebSocket事件处理
        self.websocket_client.on('command_received', self._on_remote_command)
        self.websocket_client.on('config_updated', self._on_config_update)
    
    def _on_coffee_status_change(self, status_data):
        """咖啡机状态变化处理"""
        logger.debug(f"咖啡机状态变化: {status_data}")
        
        # 通过WebSocket发送状态更新
        if self.websocket_client and self.websocket_client.is_authenticated():
            self.websocket_client.send_status(status_data)
        
        # 发送WebSocket事件到前端
        if hasattr(socketio, 'emit'):
            socketio.emit('coffee_status_update', status_data)
    
    def _on_remote_command(self, command_data):
        """远程命令处理"""
        logger.info(f"收到远程命令: {command_data}")
        
        try:
            command_type = command_data.get('command_type')
            command_id = command_data.get('command_id')
            parameters = command_data.get('parameters', {})
            
            result = self._execute_command(command_type, parameters)
            
            # 发送执行结果
            if self.websocket_client:
                self.websocket_client.send_command_result(
                    command_id, 
                    result.get('success', False),
                    result.get('data'),
                    result.get('error')
                )
                
        except Exception as e:
            logger.error(f"处理远程命令失败: {e}")
    
    def _execute_command(self, command_type, parameters):
        """执行命令"""
        try:
            if command_type == 'make_coffee':
                coffee_type = parameters.get('recipe', 'espresso')
                custom_params = parameters.get('custom_params', {})
                
                job_id = self.coffee_maker.start_coffee(coffee_type, custom_params)
                
                if job_id:
                    return {'success': True, 'data': {'job_id': job_id}}
                else:
                    return {'success': False, 'error': '无法开始制作咖啡'}
                    
            elif command_type == 'cancel_coffee':
                self.coffee_maker.cancel_current_job()
                return {'success': True, 'data': {'message': '已取消制作'}}
                
            elif command_type == 'get_status':
                status = self.coffee_maker.get_machine_status()
                return {'success': True, 'data': status}
                
            elif command_type == 'test_hardware':
                component = parameters.get('component')
                duration = parameters.get('duration', 5.0)
                
                if component == 'grinder':
                    self.hardware.start_grinder(duration)
                elif component == 'pump':
                    self.hardware.start_water_pump(duration)
                elif component == 'heater':
                    self.hardware.start_heater()
                elif component == 'steam':
                    self.hardware.start_steam(duration)
                else:
                    return {'success': False, 'error': f'未知组件: {component}'}
                
                return {'success': True, 'data': {'message': f'已启动 {component}'}}
                
            else:
                return {'success': False, 'error': f'未知命令类型: {command_type}'}
                
        except Exception as e:
            logger.error(f"执行命令失败: {e}")
            return {'success': False, 'error': str(e)}
    
    def _on_config_update(self, config_data):
        """配置更新处理"""
        logger.info(f"收到配置更新: {config_data}")
        # TODO: 实现配置更新逻辑
    
    def start_background_tasks(self):
        """启动后台任务"""
        logger.info("启动后台任务...")
        
        self.running = True
        
        # 状态上报任务
        self.status_thread = threading.Thread(target=self._status_reporter_task, daemon=True)
        self.status_thread.start()
        
        # 心跳任务
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_task, daemon=True)
        self.heartbeat_thread.start()
        
        # 命令轮询任务
        self.command_thread = threading.Thread(target=self._command_poller_task, daemon=True)
        self.command_thread.start()
        
        # 连接WebSocket
        if self.config.api_key:
            self.websocket_client.connect_async()
    
    def _status_reporter_task(self):
        """状态上报任务"""
        interval = self.config.get('server.status_report_interval', 300)  # 默认5分钟
        
        while self.running:
            try:
                if self.coffee_maker:
                    status = self.coffee_maker.get_machine_status()
                    
                    # 通过API上报状态
                    if self.api_client:
                        self.api_client.report_status(status)
                    
                    # 通过WebSocket发送状态
                    if self.websocket_client and self.websocket_client.is_authenticated():
                        self.websocket_client.send_status(status)
                
            except Exception as e:
                logger.error(f"状态上报失败: {e}")
            
            time.sleep(interval)
    
    def _heartbeat_task(self):
        """心跳任务"""
        interval = self.config.get('server.heartbeat_interval', 30)  # 默认30秒
        
        while self.running:
            try:
                # API心跳
                if self.api_client:
                    self.api_client.send_heartbeat()
                
                # WebSocket心跳
                if self.websocket_client and self.websocket_client.is_authenticated():
                    self.websocket_client.send_heartbeat()
                
            except Exception as e:
                logger.error(f"心跳发送失败: {e}")
            
            time.sleep(interval)
    
    def _command_poller_task(self):
        """命令轮询任务"""
        interval = self.config.get('server.command_poll_interval', 10)  # 默认10秒
        
        while self.running:
            try:
                if self.api_client and self.api_client.authenticated:
                    commands = self.api_client.get_pending_commands()
                    
                    for command in commands:
                        self._on_remote_command(command)
                
            except Exception as e:
                logger.error(f"命令轮询失败: {e}")
            
            time.sleep(interval)
    
    def stop_background_tasks(self):
        """停止后台任务"""
        logger.info("停止后台任务...")
        self.running = False
        
        # 断开WebSocket连接
        if self.websocket_client:
            self.websocket_client.disconnect()
    
    def cleanup(self):
        """清理资源"""
        logger.info("清理应用资源...")
        
        self.stop_background_tasks()
        
        if self.coffee_maker:
            self.coffee_maker.cleanup()
        
        if self.hardware:
            self.hardware.cleanup()
        
        if self.api_client:
            self.api_client.close()
        
        logger.info("应用资源清理完成")
    
    def run(self, host='0.0.0.0', port=5001, debug=False):
        """运行应用"""
        try:
            if not self.initialize():
                logger.error("应用初始化失败")
                return False
            
            # 启动后台任务
            self.start_background_tasks()
            
            logger.info(f"启动咖啡机客户端服务: http://{host}:{port}")
            
            # 运行Flask应用
            socketio.run(
                self.app,
                host=host,
                port=port,
                debug=debug,
                allow_unsafe_werkzeug=True
            )
            
            return True
            
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在停止...")
        except Exception as e:
            logger.error(f"运行时错误: {e}")
        finally:
            self.cleanup()
        
        return False

def signal_handler(signum, frame):
    """信号处理器"""
    logger.info(f"收到信号 {signum}，准备退出...")
    sys.exit(0)

def main():
    """主函数"""
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 创建并运行应用
    client_app = CoffeeClientApp()
    
    # 从命令行参数获取配置
    host = sys.argv[1] if len(sys.argv) > 1 else '0.0.0.0'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5001
    debug = '--debug' in sys.argv
    
    success = client_app.run(host=host, port=port, debug=debug)
    
    if not success:
        sys.exit(1)

if __name__ == '__main__':
    main()