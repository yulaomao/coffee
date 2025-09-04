"""
WebSocket Blueprint - 实时通信支持

功能：
- 设备实时状态监控
- 即时命令下发
- 连接状态管理和心跳机制
- 事件广播系统
- 管理员实时监控
"""
from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import Dict, Set, Any, Optional
from flask import request, session
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
from flask_jwt_extended import decode_token, jwt_required, get_jwt_identity
from ..extensions import db
from ..models import Device, User, MachineStatus, MachineLog, ClientCommand

logger = logging.getLogger(__name__)

# Global SocketIO instance will be initialized in extensions.py
socketio = None

# Connection tracking
device_connections: Dict[str, str] = {}  # device_no -> session_id
admin_connections: Set[str] = set()  # session_ids of admin users
session_devices: Dict[str, str] = {}  # session_id -> device_no
session_users: Dict[str, int] = {}  # session_id -> user_id


def init_socketio(app):
    """Initialize SocketIO with the Flask app"""
    global socketio
    if socketio is None:
        if not hasattr(app, 'extensions'):
            app.extensions = {}
        socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=False)
        register_socketio_handlers(socketio)
    return socketio


def register_socketio_handlers(socketio_instance):
    """Register WebSocket event handlers"""
    global socketio
    socketio = socketio_instance
    
    @socketio.on('connect')
    def on_connect(auth=None):
        """处理WebSocket连接"""
        logger.info(f'WebSocket client connected: {request.sid}')
        
        # 发送连接确认
        emit('connected', {
            'status': 'success',
            'message': 'WebSocket connected successfully',
            'server_time': datetime.utcnow().isoformat()
        })
    
    @socketio.on('disconnect')
    def on_disconnect():
        """处理WebSocket断开连接"""
        sid = request.sid
        logger.info(f'WebSocket client disconnected: {sid}')
        
        # 清理设备连接
        if sid in session_devices:
            device_no = session_devices[sid]
            if device_connections.get(device_no) == sid:
                del device_connections[device_no]
                # 广播设备离线事件
                broadcast_device_event(device_no, 'device_offline', {
                    'device_no': device_no,
                    'timestamp': datetime.utcnow().isoformat()
                })
            del session_devices[sid]
        
        # 清理管理员连接
        if sid in admin_connections:
            admin_connections.remove(sid)
        
        if sid in session_users:
            del session_users[sid]
    
    @socketio.on('device_auth')
    def on_device_auth(data):
        """设备WebSocket认证"""
        try:
            api_key = data.get('api_key')
            if not api_key:
                emit('auth_error', {'error': 'API key required'})
                return
            
            device = Device.query.filter_by(api_key=api_key).first()
            if not device:
                emit('auth_error', {'error': 'Invalid API key'})
                return
            
            # 认证成功，加入设备房间
            sid = request.sid
            device_room = f'device_{device.device_no}'
            join_room(device_room)
            
            # 记录连接
            device_connections[device.device_no] = sid
            session_devices[sid] = device.device_no
            
            # 更新设备状态
            device.last_seen = datetime.utcnow()
            device.status = 'online'
            db.session.commit()
            
            emit('auth_success', {
                'device_no': device.device_no,
                'message': 'Device authenticated successfully'
            })
            
            # 广播设备上线事件
            broadcast_device_event(device.device_no, 'device_online', {
                'device_no': device.device_no,
                'model': device.model,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            logger.info(f'Device {device.device_no} authenticated via WebSocket')
            
        except Exception as e:
            logger.error(f'Device auth error: {e}')
            emit('auth_error', {'error': 'Authentication failed'})
    
    @socketio.on('admin_auth')
    def on_admin_auth(data):
        """管理员WebSocket认证"""
        try:
            token = data.get('token')
            if not token:
                emit('auth_error', {'error': 'JWT token required'})
                return
            
            # 验证JWT token
            try:
                decoded_token = decode_token(token)
                user_info = decoded_token.get('sub')
                if not user_info or user_info.get('type') == 'device':
                    emit('auth_error', {'error': 'Invalid token type'})
                    return
                
                user_id = user_info.get('id')
                user = User.query.get(user_id)
                if not user:
                    emit('auth_error', {'error': 'User not found'})
                    return
                
                # 认证成功，加入管理员房间
                sid = request.sid
                admin_room = 'admins'
                join_room(admin_room)
                
                # 记录连接
                admin_connections.add(sid)
                session_users[sid] = user_id
                
                emit('auth_success', {
                    'user_id': user_id,
                    'username': user.username,
                    'role': user.role,
                    'message': 'Admin authenticated successfully'
                })
                
                # 发送当前在线设备列表
                online_devices = list(device_connections.keys())
                emit('online_devices', {'devices': online_devices})
                
                logger.info(f'Admin {user.username} authenticated via WebSocket')
                
            except Exception as jwt_error:
                logger.error(f'JWT decode error: {jwt_error}')
                emit('auth_error', {'error': 'Invalid token'})
                
        except Exception as e:
            logger.error(f'Admin auth error: {e}')
            emit('auth_error', {'error': 'Authentication failed'})
    
    @socketio.on('device_heartbeat')
    def on_device_heartbeat(data):
        """设备心跳"""
        sid = request.sid
        if sid not in session_devices:
            emit('error', {'error': 'Device not authenticated'})
            return
        
        device_no = session_devices[sid]
        
        try:
            device = Device.query.filter_by(device_no=device_no).first()
            if device:
                device.last_seen = datetime.utcnow()
                db.session.commit()
            
            emit('heartbeat_ack', {
                'timestamp': datetime.utcnow().isoformat(),
                'status': 'ok'
            })
            
        except Exception as e:
            logger.error(f'Heartbeat error for device {device_no}: {e}')
            emit('error', {'error': 'Heartbeat failed'})
    
    @socketio.on('device_status')
    def on_device_status(data):
        """设备状态实时上报"""
        sid = request.sid
        if sid not in session_devices:
            emit('error', {'error': 'Device not authenticated'})
            return
        
        device_no = session_devices[sid]
        
        try:
            device = Device.query.filter_by(device_no=device_no).first()
            if not device:
                emit('error', {'error': 'Device not found'})
                return
            
            # 更新设备状态
            if 'status' in data:
                device.status = data['status']
            
            # 记录详细状态
            status_record = MachineStatus(
                device_id=device.id,
                temperature=data.get('temperature'),
                water_level=data.get('water_level'),
                pressure=data.get('pressure'),
                cups_made_today=data.get('cups_made_today'),
                cups_made_total=data.get('cups_made_total'),
                running_time=data.get('running_time'),
                cleaning_status=data.get('cleaning_status'),
                material_status=data.get('material_status'),
                raw_data=data
            )
            
            db.session.add(status_record)
            db.session.commit()
            
            # 广播状态更新给管理员
            broadcast_to_admins('device_status_update', {
                'device_no': device_no,
                'status': data,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            emit('status_received', {'status': 'success'})
            
        except Exception as e:
            logger.error(f'Device status error for {device_no}: {e}')
            db.session.rollback()
            emit('error', {'error': 'Status update failed'})
    
    @socketio.on('device_log')
    def on_device_log(data):
        """设备日志实时上传"""
        sid = request.sid
        if sid not in session_devices:
            emit('error', {'error': 'Device not authenticated'})
            return
        
        device_no = session_devices[sid]
        
        try:
            device = Device.query.filter_by(device_no=device_no).first()
            if not device:
                emit('error', {'error': 'Device not found'})
                return
            
            # 记录日志
            log_entry = MachineLog(
                device_id=device.id,
                level=data.get('level', 'info'),
                message=data.get('message', ''),
                context_data=data.get('context'),
                raw_log_data=data
            )
            
            db.session.add(log_entry)
            db.session.commit()
            
            # 如果是错误或警告日志，实时推送给管理员
            if data.get('level') in ['error', 'warning']:
                broadcast_to_admins('device_log_alert', {
                    'device_no': device_no,
                    'log': data,
                    'timestamp': datetime.utcnow().isoformat()
                })
            
            emit('log_received', {'status': 'success'})
            
        except Exception as e:
            logger.error(f'Device log error for {device_no}: {e}')
            db.session.rollback()
            emit('error', {'error': 'Log upload failed'})
    
    @socketio.on('admin_send_command')
    def on_admin_send_command(data):
        """管理员通过WebSocket发送命令"""
        sid = request.sid
        if sid not in session_users:
            emit('error', {'error': 'Admin not authenticated'})
            return
        
        try:
            device_no = data.get('device_no')
            command_type = data.get('command_type')
            
            if not device_no or not command_type:
                emit('error', {'error': 'device_no and command_type required'})
                return
            
            device = Device.query.filter_by(device_no=device_no).first()
            if not device:
                emit('error', {'error': 'Device not found'})
                return
            
            # 创建命令
            command_id = f'ws_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}_{device_no}'
            command = ClientCommand(
                command_id=command_id,
                device_id=device.id,
                command_type=command_type,
                parameters=data.get('parameters', {}),
                priority=data.get('priority', 0),
                timeout_seconds=data.get('timeout_seconds'),
                created_by=session_users[sid]
            )
            
            db.session.add(command)
            db.session.commit()
            
            # 实时推送命令到设备
            if device_no in device_connections:
                device_sid = device_connections[device_no]
                socketio.emit('new_command', {
                    'command_id': command_id,
                    'type': command_type,
                    'parameters': command.parameters,
                    'priority': command.priority,
                    'timeout_seconds': command.timeout_seconds
                }, room=device_sid)
            
            emit('command_sent', {
                'command_id': command_id,
                'status': 'success',
                'message': 'Command sent to device'
            })
            
            logger.info(f'Command {command_id} sent to device {device_no} via WebSocket')
            
        except Exception as e:
            logger.error(f'Admin send command error: {e}')
            db.session.rollback()
            emit('error', {'error': 'Failed to send command'})
    
    @socketio.on('device_command_result')
    def on_device_command_result(data):
        """设备命令执行结果实时上报"""
        sid = request.sid
        if sid not in session_devices:
            emit('error', {'error': 'Device not authenticated'})
            return
        
        device_no = session_devices[sid]
        
        try:
            command_id = data.get('command_id')
            if not command_id:
                emit('error', {'error': 'command_id required'})
                return
            
            device = Device.query.filter_by(device_no=device_no).first()
            if not device:
                emit('error', {'error': 'Device not found'})
                return
            
            # 更新命令状态
            command = ClientCommand.query.filter_by(
                command_id=command_id, 
                device_id=device.id
            ).first()
            
            if command:
                command.status = 'success' if data.get('success', True) else 'failed'
                command.result = data.get('result', {})
                command.executed_at = datetime.utcnow()
                command.error_message = data.get('message') if not data.get('success', True) else None
                db.session.commit()
            
            # 实时推送结果给管理员
            broadcast_to_admins('command_result', {
                'device_no': device_no,
                'command_id': command_id,
                'result': data,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            emit('result_received', {'status': 'success'})
            
            logger.info(f'Command result received from device {device_no}: {command_id}')
            
        except Exception as e:
            logger.error(f'Command result error for {device_no}: {e}')
            db.session.rollback()
            emit('error', {'error': 'Failed to process command result'})


def broadcast_to_admins(event: str, data: dict):
    """广播消息给所有在线管理员"""
    if socketio and admin_connections:
        socketio.emit(event, data, room='admins')


def broadcast_device_event(device_no: str, event: str, data: dict):
    """广播设备事件"""
    if socketio:
        # 广播给管理员
        broadcast_to_admins(event, data)
        
        # 广播给设备（如果需要）
        if device_no in device_connections:
            device_sid = device_connections[device_no]
            socketio.emit(event, data, room=device_sid)


def send_command_to_device(device_no: str, command_data: dict):
    """向特定设备发送命令"""
    if socketio and device_no in device_connections:
        device_sid = device_connections[device_no]
        socketio.emit('new_command', command_data, room=device_sid)
        return True
    return False


def get_online_devices():
    """获取当前在线设备列表"""
    return list(device_connections.keys())


def get_online_admins():
    """获取当前在线管理员数量"""
    return len(admin_connections)


# WebSocket状态查询函数
def get_connection_stats():
    """获取连接统计信息"""
    return {
        'online_devices': len(device_connections),
        'online_admins': len(admin_connections),
        'total_connections': len(device_connections) + len(admin_connections),
        'device_list': list(device_connections.keys())
    }