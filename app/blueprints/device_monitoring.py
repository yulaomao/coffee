"""
Enhanced Device Management API - 实时监控和管理界面扩展

提供以下功能：
- 实时设备监控仪表盘
- 设备分组和过滤
- 批量操作
- 诊断工具
- 配置管理
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from flask import Blueprint, jsonify, request, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func, and_, or_
from ..extensions import db
from ..models import Device, MachineStatus, MachineLog, ClientCommand, Merchant, CommandResult, OperationLog
from ..utils.security import merchant_scope_filter

bp = Blueprint("device_monitoring", __name__, url_prefix="/api/v1/monitoring")


def _current_claims():
    """获取当前用户身份信息"""
    try:
        from flask_jwt_extended import get_jwt_identity
        claims = get_jwt_identity()
        if claims:
            return claims
            
        # 回退到session
        from flask import session
        from ..models import User
        uid = session.get("user_id")
        if uid:
            u = User.query.get(uid)
            if u:
                return {"id": u.id, "role": u.role, "merchant_id": u.merchant_id}
    except Exception:
        pass
    return None


# ========== 实时监控仪表盘 ==========

@bp.route("/dashboard/overview", methods=["GET"])
@jwt_required(optional=True)
def dashboard_overview():
    """
    实时监控仪表盘概览
    GET /api/v1/monitoring/dashboard/overview
    
    返回整体设备状态统计和关键指标
    """
    try:
        claims = _current_claims()
        if not claims:
            return jsonify({"error": "Unauthorized"}), 401
        
        # 基础设备查询（应用商户过滤）
        devices_query = merchant_scope_filter(Device.query, claims)
        
        # 设备统计
        total_devices = devices_query.count()
        online_devices = devices_query.filter(Device.status == 'online').count()
        offline_devices = devices_query.filter(Device.status == 'offline').count()
        error_devices = devices_query.filter(Device.status.like('%error%')).count()
        
        # 最近24小时状态记录
        yesterday = datetime.utcnow() - timedelta(days=1)
        recent_status = db.session.query(
            MachineStatus.device_id,
            func.count(MachineStatus.id).label('status_count'),
            func.max(MachineStatus.created_at).label('last_update'),
            func.avg(MachineStatus.temperature).label('avg_temperature'),
            func.avg(MachineStatus.water_level).label('avg_water_level'),
            func.sum(MachineStatus.cups_made_today).label('total_cups')
        ).join(Device).filter(
            MachineStatus.created_at >= yesterday
        ).group_by(MachineStatus.device_id).all()
        
        # 活跃设备（最近24小时有状态更新）
        active_devices = len([s for s in recent_status if s.last_update and s.last_update >= yesterday])
        
        # 警报统计
        error_logs_today = db.session.query(func.count(MachineLog.id)).join(Device).filter(
            MachineLog.level.in_(['error', 'warning']),
            MachineLog.created_at >= datetime.utcnow().date()
        ).scalar() or 0
        
        # 当前待执行命令数
        pending_commands = db.session.query(func.count(ClientCommand.id)).join(Device).filter(
            ClientCommand.status.in_(['pending', 'sent'])
        ).scalar() or 0
        
        # WebSocket连接状态
        websocket_stats = {"online_devices": 0, "online_admins": 0}
        try:
            from ..blueprints.websocket import get_connection_stats
            websocket_stats = get_connection_stats()
        except ImportError:
            pass
        
        return jsonify({
            "success": True,
            "overview": {
                "total_devices": total_devices,
                "online_devices": online_devices,
                "offline_devices": offline_devices,
                "error_devices": error_devices,
                "active_devices": active_devices,
                "online_rate": round((online_devices / total_devices * 100) if total_devices > 0 else 0, 2)
            },
            "metrics": {
                "error_logs_today": error_logs_today,
                "pending_commands": pending_commands,
                "avg_temperature": round(sum([s.avg_temperature or 0 for s in recent_status]) / len(recent_status), 1) if recent_status else 0,
                "total_cups_today": sum([s.total_cups or 0 for s in recent_status])
            },
            "websocket": websocket_stats,
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to get overview: {e}"}), 500


@bp.route("/dashboard/devices", methods=["GET"])
@jwt_required(optional=True)
def dashboard_devices():
    """
    设备列表视图（增强版）
    GET /api/v1/monitoring/dashboard/devices
    
    参数：
    - status: 设备状态过滤
    - search: 搜索关键词
    - group: 分组字段 (location, model, status)
    - page: 分页页码
    - per_page: 每页数量
    """
    try:
        claims = _current_claims()
        if not claims:
            return jsonify({"error": "Unauthorized"}), 401
        
        # 获取查询参数
        status_filter = request.args.get('status')
        search = request.args.get('search')
        group_by = request.args.get('group')
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 20)), 100)
        
        # 基础查询
        devices_query = merchant_scope_filter(Device.query, claims)
        
        # 应用过滤条件
        if status_filter:
            devices_query = devices_query.filter(Device.status == status_filter)
        
        if search:
            search_pattern = f"%{search}%"
            devices_query = devices_query.filter(
                or_(
                    Device.device_no.like(search_pattern),
                    Device.model.like(search_pattern),
                    Device.address.like(search_pattern)
                )
            )
        
        # 获取总数
        total = devices_query.count()
        
        # 分页查询
        devices = devices_query.order_by(Device.last_seen.desc().nullslast(), Device.created_at.desc())\
            .offset((page - 1) * per_page).limit(per_page).all()
        
        # 获取设备最新状态
        device_ids = [d.id for d in devices]
        latest_status = {}
        if device_ids:
            status_query = db.session.query(
                MachineStatus.device_id,
                MachineStatus.temperature,
                MachineStatus.water_level,
                MachineStatus.pressure,
                MachineStatus.cups_made_today,
                MachineStatus.material_status,
                MachineStatus.created_at
            ).filter(
                MachineStatus.device_id.in_(device_ids)
            ).order_by(MachineStatus.device_id, MachineStatus.created_at.desc())
            
            for status in status_query:
                if status.device_id not in latest_status:
                    latest_status[status.device_id] = {
                        'temperature': status.temperature,
                        'water_level': status.water_level,
                        'pressure': status.pressure,
                        'cups_made_today': status.cups_made_today,
                        'material_status': status.material_status,
                        'last_status_update': status.created_at.isoformat() if status.created_at else None
                    }
        
        # 构建响应数据
        device_list = []
        for device in devices:
            device_data = {
                'id': device.id,
                'device_no': device.device_no,
                'model': device.model,
                'status': device.status,
                'address': device.address,
                'scene': device.scene,
                'last_seen': device.last_seen.isoformat() if device.last_seen else None,
                'firmware_version': device.firmware_version,
                'ip_address': device.ip_address,
                'created_at': device.created_at.isoformat()
            }
            
            # 添加最新状态数据
            if device.id in latest_status:
                device_data['latest_status'] = latest_status[device.id]
            
            device_list.append(device_data)
        
        response = {
            "success": True,
            "devices": device_list,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page
            },
            "filters_applied": {
                "status": status_filter,
                "search": search
            }
        }
        
        # 如果指定分组，添加分组统计
        if group_by in ['status', 'model', 'scene']:
            groups = {}
            for device in device_list:
                group_value = device.get(group_by, 'Unknown')
                if group_value not in groups:
                    groups[group_value] = 0
                groups[group_value] += 1
            response['groups'] = groups
        
        return jsonify(response)
        
    except Exception as e:
        return jsonify({"error": f"Failed to get devices: {e}"}), 500


@bp.route("/devices/<int:device_id>/realtime", methods=["GET"])
@jwt_required(optional=True)
def device_realtime_status(device_id: int):
    """
    设备实时状态详情
    GET /api/v1/monitoring/devices/<device_id>/realtime
    """
    try:
        claims = _current_claims()
        if not claims:
            return jsonify({"error": "Unauthorized"}), 401
        
        device = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
        
        # 最近状态记录（最近1小时）
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        recent_status = MachineStatus.query.filter(
            MachineStatus.device_id == device_id,
            MachineStatus.created_at >= one_hour_ago
        ).order_by(MachineStatus.created_at.desc()).limit(60).all()
        
        # 最新状态
        latest_status = recent_status[0] if recent_status else None
        
        # 最近错误日志（最近24小时）
        yesterday = datetime.utcnow() - timedelta(days=1)
        error_logs = MachineLog.query.filter(
            MachineLog.device_id == device_id,
            MachineLog.level.in_(['error', 'warning']),
            MachineLog.created_at >= yesterday
        ).order_by(MachineLog.created_at.desc()).limit(10).all()
        
        # 待执行命令
        pending_commands = ClientCommand.query.filter(
            ClientCommand.device_id == device_id,
            ClientCommand.status.in_(['pending', 'sent'])
        ).order_by(ClientCommand.created_at.desc()).all()
        
        # 最近命令执行结果
        recent_results = CommandResult.query.filter(
            CommandResult.device_id == device_id
        ).order_by(CommandResult.created_at.desc()).limit(5).all()
        
        # WebSocket连接状态
        websocket_connected = False
        try:
            from ..blueprints.websocket import device_connections
            websocket_connected = device.device_no in device_connections
        except ImportError:
            pass
        
        return jsonify({
            "success": True,
            "device": {
                'id': device.id,
                'device_no': device.device_no,
                'model': device.model,
                'status': device.status,
                'address': device.address,
                'last_seen': device.last_seen.isoformat() if device.last_seen else None,
                'firmware_version': device.firmware_version,
                'ip_address': device.ip_address,
                'websocket_connected': websocket_connected
            },
            "current_status": {
                'temperature': latest_status.temperature if latest_status else None,
                'water_level': latest_status.water_level if latest_status else None,
                'pressure': latest_status.pressure if latest_status else None,
                'cups_made_today': latest_status.cups_made_today if latest_status else 0,
                'material_status': latest_status.material_status if latest_status else {},
                'last_update': latest_status.created_at.isoformat() if latest_status else None
            },
            "status_history": [
                {
                    'timestamp': status.created_at.isoformat(),
                    'temperature': status.temperature,
                    'water_level': status.water_level,
                    'pressure': status.pressure,
                    'cups_made_today': status.cups_made_today
                }
                for status in reversed(recent_status[-20:])  # 最近20条记录，按时间正序
            ],
            "error_logs": [
                {
                    'level': log.level,
                    'message': log.message,
                    'timestamp': log.created_at.isoformat()
                }
                for log in error_logs
            ],
            "pending_commands": [
                {
                    'command_id': cmd.command_id,
                    'type': cmd.command_type,
                    'status': cmd.status,
                    'created_at': cmd.created_at.isoformat(),
                    'priority': cmd.priority
                }
                for cmd in pending_commands
            ],
            "recent_results": [
                {
                    'command_id': result.command_id,
                    'success': result.success,
                    'message': result.message,
                    'timestamp': result.created_at.isoformat()
                }
                for result in recent_results
            ]
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to get device status: {e}"}), 500


# ========== 批量操作 ==========

@bp.route("/devices/batch/command", methods=["POST"])
@jwt_required(optional=True)
def batch_send_command():
    """
    批量发送命令到多个设备
    POST /api/v1/monitoring/devices/batch/command
    
    请求体：
    {
        "device_ids": [1, 2, 3],
        "command_type": "reboot",
        "parameters": {...},
        "priority": 1
    }
    """
    try:
        claims = _current_claims()
        if not claims:
            return jsonify({"error": "Unauthorized"}), 401
        
        data = request.get_json() or {}
        device_ids = data.get('device_ids', [])
        command_type = data.get('command_type')
        parameters = data.get('parameters', {})
        priority = data.get('priority', 0)
        
        if not device_ids or not command_type:
            return jsonify({"error": "Missing device_ids or command_type"}), 400
        
        # 验证设备权限
        devices = merchant_scope_filter(
            Device.query.filter(Device.id.in_(device_ids)), claims
        ).all()
        
        if len(devices) != len(device_ids):
            return jsonify({"error": "Some devices not found or access denied"}), 404
        
        # 创建批量命令
        commands_created = []
        batch_id = f"batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        for device in devices:
            command_id = f"{batch_id}_{device.device_no}"
            command = ClientCommand(
                command_id=command_id,
                device_id=device.id,
                command_type=command_type,
                parameters=parameters,
                priority=priority,
                created_by=claims.get('id')
            )
            db.session.add(command)
            commands_created.append(command_id)
        
        db.session.commit()
        
        # 记录批量操作日志
        try:
            db.session.add(OperationLog(
                user_id=claims.get('id', 0),
                action='batch_command',
                target_type='devices',
                target_id=None,
                raw_payload={
                    'batch_id': batch_id,
                    'device_count': len(devices),
                    'command_type': command_type,
                    'device_ids': device_ids
                }
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
        
        # 尝试通过WebSocket实时推送命令
        websocket_sent = 0
        try:
            from ..blueprints.websocket import send_command_to_device
            for device in devices:
                if send_command_to_device(device.device_no, {
                    'command_id': f"{batch_id}_{device.device_no}",
                    'type': command_type,
                    'parameters': parameters,
                    'priority': priority
                }):
                    websocket_sent += 1
        except ImportError:
            pass
        
        return jsonify({
            "success": True,
            "batch_id": batch_id,
            "commands_created": len(commands_created),
            "websocket_sent": websocket_sent,
            "message": f"Batch command sent to {len(devices)} devices"
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to send batch command: {e}"}), 500


# ========== 配置管理 ==========

@bp.route("/devices/<int:device_id>/config/template", methods=["POST"])
@jwt_required(optional=True)
def push_config_template(device_id: int):
    """
    推送配置模板到设备
    POST /api/v1/monitoring/devices/<device_id>/config/template
    
    请求体：
    {
        "template_name": "default_coffee_machine",
        "config": {...}
    }
    """
    try:
        claims = _current_claims()
        if not claims:
            return jsonify({"error": "Unauthorized"}), 401
        
        device = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
        
        data = request.get_json() or {}
        template_name = data.get('template_name')
        config = data.get('config', {})
        
        if not template_name or not config:
            return jsonify({"error": "Missing template_name or config"}), 400
        
        # 更新设备配置
        current_config = device.config or {}
        current_config.update(config)
        current_config['template_name'] = template_name
        current_config['template_applied_at'] = datetime.utcnow().isoformat()
        
        device.config = current_config
        db.session.commit()
        
        # 发送配置更新命令
        command_id = f"config_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{device.device_no}"
        command = ClientCommand(
            command_id=command_id,
            device_id=device.id,
            command_type='update_config',
            parameters={'config': config, 'template': template_name},
            priority=1,
            created_by=claims.get('id')
        )
        db.session.add(command)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"Configuration template '{template_name}' applied to device {device.device_no}",
            "command_id": command_id
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to apply config template: {e}"}), 500


# ========== 诊断工具 ==========

@bp.route("/devices/<int:device_id>/diagnostics", methods=["POST"])
@jwt_required(optional=True)
def run_diagnostics(device_id: int):
    """
    运行设备诊断
    POST /api/v1/monitoring/devices/<device_id>/diagnostics
    
    请求体：
    {
        "tests": ["connectivity", "sensors", "materials", "performance"]
    }
    """
    try:
        claims = _current_claims()
        if not claims:
            return jsonify({"error": "Unauthorized"}), 401
        
        device = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
        
        data = request.get_json() or {}
        tests = data.get('tests', ['connectivity', 'sensors'])
        
        # 创建诊断命令
        command_id = f"diag_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{device.device_no}"
        command = ClientCommand(
            command_id=command_id,
            device_id=device.id,
            command_type='run_diagnostics',
            parameters={'tests': tests, 'detailed': True},
            priority=2,  # 高优先级
            timeout_seconds=300,  # 5分钟超时
            created_by=claims.get('id')
        )
        db.session.add(command)
        db.session.commit()
        
        # 记录诊断操作
        try:
            db.session.add(OperationLog(
                user_id=claims.get('id', 0),
                action='run_diagnostics',
                target_type='device',
                target_id=device.id,
                raw_payload={'tests': tests, 'command_id': command_id}
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
        
        return jsonify({
            "success": True,
            "message": f"Diagnostics started for device {device.device_no}",
            "command_id": command_id,
            "tests": tests,
            "estimated_duration": "2-5 minutes"
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to start diagnostics: {e}"}), 500


# ========== 统计和分析 ==========

@bp.route("/analytics/performance", methods=["GET"])
@jwt_required(optional=True)
def analytics_performance():
    """
    性能分析数据
    GET /api/v1/monitoring/analytics/performance?days=7
    """
    try:
        claims = _current_claims()
        if not claims:
            return jsonify({"error": "Unauthorized"}), 401
        
        days = int(request.args.get('days', 7))
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # 设备性能统计
        device_stats = db.session.query(
            Device.id,
            Device.device_no,
            Device.model,
            func.count(MachineStatus.id).label('status_reports'),
            func.avg(MachineStatus.temperature).label('avg_temperature'),
            func.avg(MachineStatus.water_level).label('avg_water_level'),
            func.sum(MachineStatus.cups_made_today).label('total_cups'),
            func.avg(MachineStatus.running_time).label('avg_running_time')
        ).join(MachineStatus).filter(
            MachineStatus.created_at >= start_date
        ).group_by(Device.id, Device.device_no, Device.model).all()
        
        # 错误统计
        error_stats = db.session.query(
            Device.device_no,
            MachineLog.level,
            func.count(MachineLog.id).label('error_count')
        ).join(MachineLog).filter(
            MachineLog.created_at >= start_date,
            MachineLog.level.in_(['error', 'warning'])
        ).group_by(Device.device_no, MachineLog.level).all()
        
        # 命令执行统计
        command_stats = db.session.query(
            Device.device_no,
            ClientCommand.status,
            func.count(ClientCommand.id).label('command_count')
        ).join(ClientCommand).filter(
            ClientCommand.created_at >= start_date
        ).group_by(Device.device_no, ClientCommand.status).all()
        
        return jsonify({
            "success": True,
            "period": f"Last {days} days",
            "device_performance": [
                {
                    'device_no': stat.device_no,
                    'model': stat.model,
                    'status_reports': stat.status_reports,
                    'avg_temperature': round(stat.avg_temperature, 1) if stat.avg_temperature else None,
                    'avg_water_level': round(stat.avg_water_level, 1) if stat.avg_water_level else None,
                    'total_cups': stat.total_cups or 0,
                    'avg_running_time': round(stat.avg_running_time / 3600, 1) if stat.avg_running_time else 0  # hours
                }
                for stat in device_stats
            ],
            "error_summary": [
                {
                    'device_no': stat.device_no,
                    'level': stat.level,
                    'count': stat.error_count
                }
                for stat in error_stats
            ],
            "command_summary": [
                {
                    'device_no': stat.device_no,
                    'status': stat.status,
                    'count': stat.command_count
                }
                for stat in command_stats
            ]
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to get analytics: {e}"}), 500