"""
Client API Blueprint - 专用于设备端通信的RESTful API接口

包含以下接口组：
- 认证接口: /api/v1/client/auth, /api/v1/client/register
- 状态接口: /api/v1/client/status, /api/v1/client/stats
- 控制接口: /api/v1/client/commands, /api/v1/client/command-result
- 配置接口: /api/v1/client/config
- 维护接口: /api/v1/client/logs, /api/v1/client/update
"""
from __future__ import annotations
import uuid
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from functools import wraps
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from ..extensions import db
from ..models import Device, MachineStatus, MachineLog, ClientCommand, Merchant, UpgradePackage, RemoteCommand, CommandResult
from ..utils.security import hash_password
from ..utils.security_enhanced import (
    rate_limit, strict_rate_limiter, default_rate_limiter,
    require_signature, audit_security_event, SecurityAuditLogger,
    generate_api_key, add_security_headers
)
import logging

bp = Blueprint("client_api", __name__, url_prefix="/api/v1/client")
logger = logging.getLogger(__name__)


# 在每个响应中添加安全头部
@bp.after_request
def after_request(response):
    return add_security_headers(response)


def api_key_required(f):
    """API Key认证装饰器（增强版）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not api_key:
            SecurityAuditLogger.log_security_event(
                'api_key_missing',
                {'endpoint': request.endpoint, 'ip': request.remote_addr},
                'warning'
            )
            return jsonify({"error": "API key required", "code": "MISSING_API_KEY"}), 401
            
        device = Device.query.filter_by(api_key=api_key).first()
        if not device:
            SecurityAuditLogger.log_security_event(
                'api_key_invalid',
                {'endpoint': request.endpoint, 'ip': request.remote_addr, 'api_key_hash': api_key[:8] + '***'},
                'warning'
            )
            return jsonify({"error": "Invalid API key", "code": "INVALID_API_KEY"}), 401
            
        # 更新设备最后访问时间
        device.last_seen = datetime.utcnow()
        device.ip_address = request.remote_addr
        db.session.commit()
        
        # 将设备信息传递给视图函数
        request.current_device = device
        return f(*args, **kwargs)
    return decorated


# ========== 认证接口 ==========

@bp.route("/register", methods=["POST"])
@rate_limit(strict_rate_limiter)  # 严格速率限制
@audit_security_event('device_registration', 'info')
def register_device():
    """
    设备注册接口（增强安全版）
    POST /api/v1/client/register
    
    请求体:
    {
        "device_no": "CM001",
        "model": "CoffeeMaster Pro",
        "firmware_version": "1.0.0",
        "pre_shared_key": "default_registration_key"
    }
    """
    try:
        data = request.get_json() or {}
        
        device_no = data.get("device_no")
        pre_shared_key = data.get("pre_shared_key")
        
        if not device_no or not pre_shared_key:
            return jsonify({
                "error": "Missing device_no or pre_shared_key", 
                "code": "MISSING_PARAMS"
            }), 400
            
        # 验证预共享密钥 (在生产环境中应该从配置中读取)
        if pre_shared_key != current_app.config.get("DEVICE_REGISTRATION_KEY", "default_registration_key"):
            SecurityAuditLogger.log_security_event(
                'device_registration_invalid_psk',
                {'device_no': device_no, 'ip': request.remote_addr},
                'warning'
            )
            return jsonify({
                "error": "Invalid pre-shared key", 
                "code": "INVALID_PSK"
            }), 403
            
        # 检查设备是否已存在
        existing_device = Device.query.filter_by(device_no=device_no).first()
        if existing_device:
            if existing_device.api_key:
                SecurityAuditLogger.log_security_event(
                    'device_registration_duplicate',
                    {'device_no': device_no, 'ip': request.remote_addr},
                    'warning'
                )
                return jsonify({
                    "error": "Device already registered", 
                    "code": "ALREADY_REGISTERED"
                }), 409
        else:
            # 创建新设备 (分配给默认商户)
            default_merchant = Merchant.query.first()
            if not default_merchant:
                return jsonify({
                    "error": "No merchant available", 
                    "code": "NO_MERCHANT"
                }), 500
                
            existing_device = Device(
                device_no=device_no,
                merchant_id=default_merchant.id,
                model=data.get("model"),
                firmware_version=data.get("firmware_version"),
                software_version=data.get("software_version"),
                status="offline"
            )
            db.session.add(existing_device)
            
        # 生成安全的API密钥
        api_key = generate_api_key()
        existing_device.api_key = api_key
        existing_device.api_key_created_at = datetime.utcnow()
        existing_device.last_seen = datetime.utcnow()
        existing_device.ip_address = request.remote_addr
        
        db.session.commit()
        
        SecurityAuditLogger.log_security_event(
            'device_registration_success',
            {'device_no': device_no, 'device_id': existing_device.id},
            'info'
        )
        
        return jsonify({
            "success": True,
            "device_id": existing_device.device_no,
            "api_key": api_key,
            "message": "Device registered successfully"
        })
        
    except Exception as e:
        logger.error(f"Device registration error: {e}")
        db.session.rollback()
        return jsonify({
            "error": "Registration failed", 
            "code": "REGISTRATION_ERROR"
        }), 500


@bp.route("/auth", methods=["POST"])
@rate_limit(default_rate_limiter)
@api_key_required
@audit_security_event('device_authentication', 'info')
def authenticate_device():
    """
    设备认证获取JWT令牌
    POST /api/v1/client/auth
    
    Headers: X-API-Key: <api_key>
    """
    try:
        device = request.current_device
        
        # 创建JWT令牌
        token_data = {
            "device_id": device.id,
            "device_no": device.device_no,
            "merchant_id": device.merchant_id,
            "type": "device"
        }
        
        access_token = create_access_token(identity=token_data)
        
        SecurityAuditLogger.log_security_event(
            'device_authentication_success',
            {'device_no': device.device_no, 'device_id': device.id},
            'info'
        )
        
        return jsonify({
            "success": True,
            "access_token": access_token,
            "device_info": {
                "device_no": device.device_no,
                "model": device.model,
                "status": device.status,
                "firmware_version": device.firmware_version,
                "software_version": device.software_version
            }
        })
        
    except Exception as e:
        logger.error(f"Device authentication error: {e}")
        return jsonify({
            "error": "Authentication failed", 
            "code": "AUTH_ERROR"
        }), 500


# ========== 状态接口 ==========

@bp.route("/status", methods=["POST"])
@rate_limit(default_rate_limiter)
@api_key_required
def report_status():
    """
    上报设备状态
    POST /api/v1/client/status
    
    Headers: X-API-Key: <api_key>
    """
    try:
        device = request.current_device
        data = request.get_json() or {}
        
        # 更新设备基础状态
        if "status" in data:
            device.status = data["status"]
        
        # 记录详细状态
        status_record = MachineStatus(
            device_id=device.id,
            temperature=data.get("temperature"),
            water_level=data.get("water_level"),
            pressure=data.get("pressure"),
            cups_made_today=data.get("cups_made_today"),
            cups_made_total=data.get("cups_made_total"),
            running_time=data.get("running_time"),
            cleaning_status=data.get("cleaning_status"),
            material_status=data.get("material_status"),
            raw_data=data.get("raw_data", data)
        )
        
        db.session.add(status_record)
        db.session.commit()
        
        # 实时推送状态到WebSocket
        try:
            from .websocket import broadcast_to_admins
            broadcast_to_admins('device_status_update', {
                'device_no': device.device_no,
                'status': data,
                'timestamp': datetime.utcnow().isoformat()
            })
        except ImportError:
            pass  # WebSocket not available
        
        return jsonify({
            "success": True,
            "message": "Status reported successfully"
        })
        
    except Exception as e:
        logger.error(f"Status report error: {e}")
        db.session.rollback()
        return jsonify({
            "error": "Failed to report status", 
            "code": "STATUS_ERROR"
        }), 500


@bp.route("/stats", methods=["GET"])
@rate_limit(default_rate_limiter)
@api_key_required
def get_stats():
    """获取设备统计信息"""
    try:
        device = request.current_device
        
        # 获取最近的状态记录
        latest_status = MachineStatus.query.filter_by(device_id=device.id)\
            .order_by(MachineStatus.created_at.desc()).first()
        
        # 今日统计 
        today = datetime.utcnow().date()
        today_stats = MachineStatus.query.filter(
            MachineStatus.device_id == device.id,
            MachineStatus.created_at >= today
        ).order_by(MachineStatus.created_at.desc()).first()
        
        return jsonify({
            "success": True,
            "device_info": {
                "device_no": device.device_no,
                "status": device.status,
                "last_seen": device.last_seen.isoformat() if device.last_seen else None
            },
            "current_status": {
                "temperature": latest_status.temperature if latest_status else None,
                "water_level": latest_status.water_level if latest_status else None,
                "pressure": latest_status.pressure if latest_status else None,
                "material_status": latest_status.material_status if latest_status else None
            } if latest_status else None,
            "daily_stats": {
                "cups_made": today_stats.cups_made_today if today_stats else 0,
                "running_time": today_stats.running_time if today_stats else 0
            } if today_stats else {"cups_made": 0, "running_time": 0}
        })
        
    except Exception as e:
        logger.error(f"Get stats error: {e}")
        return jsonify({
            "error": "Failed to get stats", 
            "code": "STATS_ERROR"
        }), 500


# ========== 控制接口 ==========

@bp.route("/commands", methods=["GET"])
@rate_limit(default_rate_limiter)
@api_key_required
def get_commands():
    """获取待执行命令"""
    try:
        device = request.current_device
        
        # 获取待执行的命令
        pending_commands = []
        
        # 新的ClientCommand
        client_commands = ClientCommand.query.filter(
            ClientCommand.device_id == device.id,
            ClientCommand.status.in_(["pending", "sent"])
        ).order_by(ClientCommand.priority.desc(), ClientCommand.created_at.asc()).limit(10).all()
        
        for cmd in client_commands:
            pending_commands.append({
                "command_id": cmd.command_id,
                "type": cmd.command_type,
                "parameters": cmd.parameters or {},
                "priority": cmd.priority,
                "created_at": cmd.created_at.isoformat(),
                "timeout_seconds": cmd.timeout_seconds
            })
            # 标记为已发送
            cmd.status = "sent"
        
        # 兼容旧的RemoteCommand  
        remote_commands = RemoteCommand.query.filter(
            RemoteCommand.device_id == device.id,
            RemoteCommand.status == "pending"
        ).limit(5).all()
        
        for cmd in remote_commands:
            pending_commands.append({
                "command_id": cmd.command_id,
                "type": cmd.command_type,
                "parameters": cmd.payload or {},
                "priority": 0,
                "created_at": cmd.created_at.isoformat(),
                "timeout_seconds": None
            })
            # 标记为已发送
            cmd.status = "sent"
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "commands": pending_commands,
            "count": len(pending_commands)
        })
        
    except Exception as e:
        logger.error(f"Get commands error: {e}")
        db.session.rollback()
        return jsonify({
            "error": "Failed to get commands", 
            "code": "COMMANDS_ERROR"
        }), 500


@bp.route("/command-result", methods=["POST"])
@rate_limit(default_rate_limiter)
@api_key_required
def report_command_result():
    """上报命令执行结果"""
    try:
        device = request.current_device
        data = request.get_json() or {}
        
        command_id = data.get("command_id")
        if not command_id:
            return jsonify({
                "error": "Missing command_id", 
                "code": "MISSING_COMMAND_ID"
            }), 400
        
        success = data.get("success", True)
        result = data.get("result", {})
        message = data.get("message", "")
        
        # 查找ClientCommand
        client_command = ClientCommand.query.filter_by(command_id=command_id, device_id=device.id).first()
        if client_command:
            client_command.status = "success" if success else "failed"
            client_command.result = result
            client_command.executed_at = datetime.utcnow()
            client_command.error_message = message if not success else None
        
        # 查找RemoteCommand (兼容)
        remote_command = RemoteCommand.query.filter_by(command_id=command_id, device_id=device.id).first()
        if remote_command:
            remote_command.status = "success" if success else "fail"
            remote_command.result_payload = result
            remote_command.result_at = datetime.utcnow()
        
        # 记录CommandResult
        command_result = CommandResult(
            command_id=command_id,
            device_id=device.id,
            success=success,
            message=message,
            raw_payload=data
        )
        
        db.session.add(command_result)
        db.session.commit()
        
        # 实时推送结果到WebSocket
        try:
            from .websocket import broadcast_to_admins
            broadcast_to_admins('command_result', {
                'device_no': device.device_no,
                'command_id': command_id,
                'result': data,
                'timestamp': datetime.utcnow().isoformat()
            })
        except ImportError:
            pass  # WebSocket not available
        
        return jsonify({
            "success": True,
            "message": "Command result reported successfully"
        })
        
    except Exception as e:
        logger.error(f"Report command result error: {e}")
        db.session.rollback()
        return jsonify({
            "error": "Failed to report command result", 
            "code": "RESULT_ERROR"
        }), 500


# ========== 配置接口 ==========

@bp.route("/config", methods=["GET"])
@rate_limit(default_rate_limiter)
@api_key_required
def get_config():
    """获取设备配置"""
    try:
        device = request.current_device
        
        config = device.config or {}
        
        # 默认配置
        default_config = {
            "heartbeat_interval": 30,  # seconds
            "status_report_interval": 300,  # seconds
            "command_poll_interval": 10,  # seconds
            "log_level": "info",
            "auto_cleaning_enabled": True,
            "auto_cleaning_interval": 7200,  # seconds
            "temperature_thresholds": {
                "min": 80.0,
                "max": 95.0
            },
            "water_level_threshold": 10.0,
            "pressure_thresholds": {
                "min": 8.0,
                "max": 12.0
            }
        }
        
        # 合并默认配置和设备特定配置
        final_config = {**default_config, **config}
        
        return jsonify({
            "success": True,
            "config": final_config,
            "updated_at": device.updated_at.isoformat()
        })
        
    except Exception as e:
        logger.error(f"Get config error: {e}")
        return jsonify({
            "error": "Failed to get config", 
            "code": "CONFIG_ERROR"
        }), 500


@bp.route("/config", methods=["PUT"])
@rate_limit(strict_rate_limiter)  # 配置更新使用严格限制
@api_key_required 
def update_config():
    """更新设备配置（有限支持设备端配置更新）"""
    try:
        device = request.current_device
        data = request.get_json() or {}
        
        # 只允许设备更新某些配置项
        allowed_keys = ["log_level", "custom_settings", "device_specific_params"]
        
        current_config = device.config or {}
        
        for key, value in data.items():
            if key in allowed_keys:
                current_config[key] = value
                
        device.config = current_config
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Configuration updated successfully"
        })
        
    except Exception as e:
        logger.error(f"Update config error: {e}")
        db.session.rollback()
        return jsonify({
            "error": "Failed to update config", 
            "code": "CONFIG_UPDATE_ERROR"
        }), 500


# ========== 维护接口 ==========

@bp.route("/logs", methods=["POST"])
@rate_limit(default_rate_limiter)
@api_key_required
def upload_logs():
    """上传设备日志"""
    try:
        device = request.current_device
        data = request.get_json() or {}
        
        logs = data.get("logs", [])
        if not logs:
            return jsonify({
                "error": "No logs provided", 
                "code": "NO_LOGS"
            }), 400
        
        # 批量插入日志
        log_records = []
        for log_entry in logs:
            if isinstance(log_entry, dict):
                log_record = MachineLog(
                    device_id=device.id,
                    level=log_entry.get("level", "info"),
                    message=log_entry.get("message", ""),
                    context_data=log_entry.get("context"),
                    raw_log_data=log_entry
                )
                log_records.append(log_record)
        
        if log_records:
            db.session.add_all(log_records)
            db.session.commit()
            
            # 检查是否有错误或警告日志需要实时推送
            error_logs = [log for log in logs if isinstance(log, dict) and log.get('level') in ['error', 'warning']]
            if error_logs:
                try:
                    from .websocket import broadcast_to_admins
                    broadcast_to_admins('device_log_alert', {
                        'device_no': device.device_no,
                        'logs': error_logs,
                        'timestamp': datetime.utcnow().isoformat()
                    })
                except ImportError:
                    pass  # WebSocket not available
        
        return jsonify({
            "success": True,
            "message": f"Uploaded {len(log_records)} log entries",
            "processed": len(log_records)
        })
        
    except Exception as e:
        logger.error(f"Upload logs error: {e}")
        db.session.rollback()
        return jsonify({
            "error": "Failed to upload logs", 
            "code": "LOG_UPLOAD_ERROR"
        }), 500


@bp.route("/update", methods=["GET"])
@rate_limit(default_rate_limiter)
@api_key_required
def check_update():
    """检查更新"""
    try:
        device = request.current_device
        
        # 查找最新的升级包
        latest_package = UpgradePackage.query.order_by(UpgradePackage.created_at.desc()).first()
        
        if not latest_package:
            return jsonify({
                "success": True,
                "update_available": False,
                "message": "No updates available"
            })
        
        # 检查版本是否更新
        current_version = device.firmware_version or "0.0.0"
        latest_version = latest_package.version
        
        # 简单版本比较
        update_available = current_version != latest_version
        
        response = {
            "success": True,
            "update_available": update_available,
            "current_version": current_version,
            "latest_version": latest_version
        }
        
        if update_available:
            response.update({
                "package_info": {
                    "version": latest_package.version,
                    "file_name": latest_package.file_name,
                    "md5": latest_package.md5,
                    "created_at": latest_package.created_at.isoformat()
                },
                "download_url": f"/api/upgrades/download/{latest_package.id}"
            })
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Check update error: {e}")
        return jsonify({
            "error": "Failed to check update", 
            "code": "UPDATE_CHECK_ERROR"
        }), 500


# ========== 健康检查和调试接口 ==========

@bp.route("/ping", methods=["GET"])
@rate_limit(default_rate_limiter)
@api_key_required
def ping():
    """健康检查接口"""
    device = request.current_device
    return jsonify({
        "success": True,
        "message": "pong",
        "device_no": device.device_no,
        "server_time": datetime.utcnow().isoformat()
    })


@bp.route("/websocket/status", methods=["GET"])
@api_key_required
def websocket_status():
    """获取WebSocket连接状态"""
    device = request.current_device
    
    try:
        from .websocket import get_connection_stats, device_connections
        
        stats = get_connection_stats()
        is_connected = device.device_no in device_connections
        
        return jsonify({
            "success": True,
            "websocket_connected": is_connected,
            "device_no": device.device_no,
            "connection_stats": stats
        })
        
    except Exception as e:
        logger.error(f"WebSocket status error: {e}")
        return jsonify({
            "success": False,
            "websocket_connected": False,
            "error": "Failed to get WebSocket status"
        })


# ========== WebSocket 管理接口 ==========

@bp.route("/admin/websocket/stats", methods=["GET"])
def admin_websocket_stats():
    """管理员获取WebSocket连接统计"""
    try:
        from .websocket import get_connection_stats
        stats = get_connection_stats()
        
        return jsonify({
            "success": True,
            "stats": stats
        })
        
    except Exception as e:
        logger.error(f"Admin WebSocket stats error: {e}")
        return jsonify({
            "success": False,
            "error": "Failed to get WebSocket stats"
        })


# ========== 错误处理 ==========

@bp.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Endpoint not found",
        "code": "NOT_FOUND"
    }), 404


@bp.errorhandler(405)
def method_not_allowed(error):
    return jsonify({
        "error": "Method not allowed",
        "code": "METHOD_NOT_ALLOWED"
    }), 405


@bp.errorhandler(400)
def bad_request(error):
    return jsonify({
        "error": "Bad request",
        "code": "BAD_REQUEST"
    }), 400


@bp.errorhandler(429)
def rate_limit_exceeded(error):
    return jsonify({
        "error": "Rate limit exceeded",
        "code": "RATE_LIMIT_EXCEEDED",
        "message": "Too many requests. Please try again later."
    }), 429