"""
咖啡机客户端应用 - 主应用模块

提供Flask Web界面和后台服务的集成
"""
import os
import json
import logging

# 全局对象
socketio = None

try:
    from flask import Flask
    from flask_socketio import SocketIO
    _flask_available = True
except ImportError:
    _flask_available = False

def load_config():
    """加载配置文件"""
    config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config')
    
    # 加载默认配置
    default_config_path = os.path.join(config_dir, 'default.json')
    with open(default_config_path, 'r', encoding='utf-8') as f:
        default_config = json.load(f)
    
    # 加载设备配置
    device_config_path = os.path.join(config_dir, 'device.json')
    with open(device_config_path, 'r', encoding='utf-8') as f:
        device_config = json.load(f)
    
    # 合并配置
    config = {**default_config, 'device_config': device_config}
    return config

def setup_logging(config):
    """设置日志"""
    log_level = getattr(logging, config.get('logging', {}).get('level', 'INFO'))
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(log_dir, 'client.log'), encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

def create_app():
    """创建Flask应用"""
    if not _flask_available:
        raise ImportError("Flask不可用，请安装依赖: pip install -r requirements.txt")
    
    app = Flask(__name__)
    
    # 加载配置
    config = load_config()
    app.config['CLIENT_CONFIG'] = config
    app.config['SECRET_KEY'] = 'coffee-client-secret-key-change-in-production'
    
    # 设置日志
    setup_logging(config)
    
    # 初始化SocketIO
    global socketio
    socketio = SocketIO()
    socketio.init_app(app, cors_allowed_origins="*")
    
    # 注册蓝图
    from .web.routes import bp as web_bp
    app.register_blueprint(web_bp)
    
    return app