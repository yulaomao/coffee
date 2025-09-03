"""
Web路由模块

提供咖啡机客户端的Web界面路由
"""
import logging
from flask import Blueprint, render_template, jsonify, request, current_app
from flask_socketio import emit
from datetime import datetime

logger = logging.getLogger(__name__)

bp = Blueprint('web', __name__)

# 全局变量，将在应用启动时设置
coffee_maker = None
hardware = None
api_client = None
websocket_client = None

def set_components(cm, hw, api, ws):
    """设置全局组件引用"""
    global coffee_maker, hardware, api_client, websocket_client
    coffee_maker = cm
    hardware = hw
    api_client = api
    websocket_client = ws

@bp.route('/')
def index():
    """主界面"""
    return render_template('index.html')

@bp.route('/coffee')
def coffee_select():
    """咖啡选择界面"""
    coffees = coffee_maker.get_available_coffees() if coffee_maker else {}
    return render_template('coffee_select.html', coffees=coffees)

@bp.route('/making')
def making():
    """制作过程界面"""
    return render_template('making.html')

@bp.route('/settings')
def settings():
    """设置界面"""
    config = current_app.config.get('CLIENT_CONFIG', {})
    return render_template('settings.html', config=config)

@bp.route('/admin')
def admin():
    """管理员界面"""
    return render_template('admin.html')

# API路由

@bp.route('/api/status')
def get_status():
    """获取机器状态"""
    try:
        if coffee_maker:
            status = coffee_maker.get_machine_status()
            return jsonify({
                'success': True,
                'status': status
            })
        else:
            return jsonify({
                'success': False,
                'error': '咖啡机未初始化'
            })
    except Exception as e:
        logger.error(f"获取状态失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@bp.route('/api/coffee/start', methods=['POST'])
def start_coffee():
    """开始制作咖啡"""
    try:
        data = request.get_json() or {}
        coffee_type = data.get('coffee_type')
        custom_params = data.get('custom_params', {})
        
        if not coffee_type:
            return jsonify({
                'success': False,
                'error': '请指定咖啡类型'
            })
        
        if not coffee_maker:
            return jsonify({
                'success': False,
                'error': '咖啡机未初始化'
            })
        
        job_id = coffee_maker.start_coffee(coffee_type, custom_params)
        
        if job_id:
            return jsonify({
                'success': True,
                'job_id': job_id
            })
        else:
            return jsonify({
                'success': False,
                'error': '无法开始制作咖啡'
            })
            
    except Exception as e:
        logger.error(f"开始制作咖啡失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@bp.route('/api/coffee/cancel', methods=['POST'])
def cancel_coffee():
    """取消制作咖啡"""
    try:
        if coffee_maker:
            coffee_maker.cancel_current_job()
            return jsonify({
                'success': True,
                'message': '已取消制作'
            })
        else:
            return jsonify({
                'success': False,
                'error': '咖啡机未初始化'
            })
    except Exception as e:
        logger.error(f"取消制作失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@bp.route('/api/coffees')
def get_coffees():
    """获取可用咖啡类型"""
    try:
        if coffee_maker:
            coffees = coffee_maker.get_available_coffees()
            return jsonify({
                'success': True,
                'coffees': coffees
            })
        else:
            return jsonify({
                'success': False,
                'error': '咖啡机未初始化'
            })
    except Exception as e:
        logger.error(f"获取咖啡类型失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@bp.route('/api/hardware/status')
def get_hardware_status():
    """获取硬件状态"""
    try:
        if hardware:
            if hasattr(hardware, 'get_status'):
                status = hardware.get_status()
            else:
                status = {
                    'temperature': hardware.get_temperature(),
                    'water_level': hardware.get_water_level(),
                    'pressure': hardware.get_pressure()
                }
            
            return jsonify({
                'success': True,
                'hardware': status
            })
        else:
            return jsonify({
                'success': False,
                'error': '硬件未初始化'
            })
    except Exception as e:
        logger.error(f"获取硬件状态失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@bp.route('/api/connection/status')
def get_connection_status():
    """获取连接状态"""
    try:
        api_connected = api_client.is_healthy() if api_client else False
        websocket_connected = websocket_client.is_connected() if websocket_client else False
        
        return jsonify({
            'success': True,
            'connections': {
                'api': api_connected,
                'websocket': websocket_connected,
                'api_authenticated': api_client.authenticated if api_client else False,
                'websocket_authenticated': websocket_client.is_authenticated() if websocket_client else False
            }
        })
    except Exception as e:
        logger.error(f"获取连接状态失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@bp.route('/api/test/hardware', methods=['POST'])
def test_hardware():
    """测试硬件组件"""
    try:
        data = request.get_json() or {}
        component = data.get('component')
        duration = float(data.get('duration', 5.0))
        
        if not hardware:
            return jsonify({
                'success': False,
                'error': '硬件未初始化'
            })
        
        if component == 'grinder':
            hardware.start_grinder(duration)
        elif component == 'pump':
            hardware.start_water_pump(duration)
        elif component == 'heater':
            hardware.start_heater()
        elif component == 'steam':
            hardware.start_steam(duration)
        else:
            return jsonify({
                'success': False,
                'error': f'未知组件: {component}'
            })
        
        return jsonify({
            'success': True,
            'message': f'已启动 {component}'
        })
        
    except Exception as e:
        logger.error(f"测试硬件失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@bp.route('/api/config', methods=['GET', 'POST'])
def config_manage():
    """配置管理"""
    try:
        config = current_app.config.get('CLIENT_CONFIG', {})
        
        if request.method == 'GET':
            return jsonify({
                'success': True,
                'config': config
            })
        else:
            # POST - 更新配置
            new_config = request.get_json() or {}
            # TODO: 实现配置更新逻辑
            return jsonify({
                'success': True,
                'message': '配置已更新'
            })
            
    except Exception as e:
        logger.error(f"配置管理失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

# WebSocket事件处理
from .. import socketio

@socketio.on('request_status')
def handle_status_request():
    """处理状态请求"""
    try:
        if coffee_maker:
            status = coffee_maker.get_machine_status()
            emit('status_update', status)
        else:
            emit('error', {'message': '咖啡机未初始化'})
    except Exception as e:
        logger.error(f"WebSocket状态请求失败: {e}")
        emit('error', {'message': str(e)})

@socketio.on('start_coffee')
def handle_start_coffee(data):
    """处理开始制作咖啡"""
    try:
        coffee_type = data.get('coffee_type')
        custom_params = data.get('custom_params', {})
        
        if not coffee_type:
            emit('error', {'message': '请指定咖啡类型'})
            return
        
        if not coffee_maker:
            emit('error', {'message': '咖啡机未初始化'})
            return
        
        job_id = coffee_maker.start_coffee(coffee_type, custom_params)
        
        if job_id:
            emit('coffee_started', {'job_id': job_id})
        else:
            emit('error', {'message': '无法开始制作咖啡'})
            
    except Exception as e:
        logger.error(f"WebSocket开始制作咖啡失败: {e}")
        emit('error', {'message': str(e)})

@socketio.on('cancel_coffee')
def handle_cancel_coffee():
    """处理取消制作咖啡"""
    try:
        if coffee_maker:
            coffee_maker.cancel_current_job()
            emit('coffee_cancelled', {'message': '已取消制作'})
        else:
            emit('error', {'message': '咖啡机未初始化'})
    except Exception as e:
        logger.error(f"WebSocket取消制作失败: {e}")
        emit('error', {'message': str(e)})