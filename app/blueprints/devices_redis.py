"""
设备管理 API（Redis版本）- 渐进式替换原有SQLAlchemy版本

主要接口:
- GET /api/devices - 设备列表
- GET /api/devices/<device_no> - 设备详情  
- PATCH /api/devices/<device_no> - 更新设备
- POST /api/devices/commands - 批量设备命令
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Dict, List
from flask import Blueprint, jsonify, request, session
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import User  # 保留用户模型用于会话处理
from ..services.device_service import DeviceService, DeviceStatsService
from ..redis_adapters import device_adapter, command_adapter

bp = Blueprint("devices_redis", __name__)


def _current_claims():
    """优先使用 JWT 身份；若无，则回退到会话用户。"""
    try:
        claims = get_jwt_identity()
    except Exception:
        claims = None
    if claims:
        return claims
    uid = session.get("user_id")
    if uid:
        u = User.query.get(uid)
        if u:
            return {"id": u.id, "role": u.role, "merchant_id": u.merchant_id}
    return None


def _merchant_filter(merchant_id_filter: Any, claims: Dict[str, Any]) -> Any:
    """商户权限过滤"""
    user_role = claims.get("role", "")
    user_merchant_id = claims.get("merchant_id")
    
    # 超级管理员可以访问所有
    if user_role == "superadmin":
        return merchant_id_filter
    
    # 其他角色只能访问自己商户的数据
    return user_merchant_id


@bp.route("/api/devices/redis")
@jwt_required(optional=True)
def list_devices():
    """Redis版本的设备列表接口"""
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    
    # 获取查询参数
    search = request.args.get("search")
    status = request.args.get("status")
    merchant_id_param = request.args.get("merchant_id")
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    fmt = request.args.get("format")
    
    # 应用商户权限过滤
    merchant_id = None
    if merchant_id_param:
        try:
            merchant_id = int(merchant_id_param)
            # 权限检查
            allowed_merchant_id = _merchant_filter(merchant_id, claims)
            if allowed_merchant_id and allowed_merchant_id != merchant_id:
                merchant_id = allowed_merchant_id
        except:
            pass
    else:
        merchant_id = _merchant_filter(None, claims)
    
    # 调用设备服务
    result = DeviceService.list_devices(
        merchant_id=merchant_id,
        status=status,
        search=search,
        page=page,
        per_page=per_page
    )
    
    if fmt == "csv":
        from ..utils.helpers import csv_response
        rows = []
        for d in result["items"]:
            rows.append([
                d.get("device_no", ""), 
                d.get("model", ""), 
                d.get("status", ""),
                d.get("last_seen", ""),
                d.get("address", ""), 
                d.get("scene", ""), 
                d.get("customer_code", "")
            ])
        return csv_response(
            ["device_no", "model", "status", "last_seen", "address", "scene", "customer_code"], 
            rows, 
            filename="devices.csv"
        )
    
    return jsonify(result)


@bp.route("/api/devices/redis/<string:device_no>")
@jwt_required(optional=True)  
def get_device(device_no: str):
    """获取单个设备详情（Redis版本）"""
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    
    device = DeviceService.get_device_by_no(device_no)
    if not device:
        return jsonify({"msg": "device not found"}), 404
    
    # 权限检查
    device_merchant_id = device.get('merchant_id')
    allowed_merchant_id = _merchant_filter(device_merchant_id, claims)
    if allowed_merchant_id and str(allowed_merchant_id) != str(device_merchant_id):
        return jsonify({"msg": "access denied"}), 403
    
    return jsonify(device)


@bp.route("/api/devices/redis/<string:device_no>", methods=["PATCH"])
@jwt_required(optional=True)
def update_device(device_no: str):
    """更新设备信息（Redis版本）"""
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    
    device = DeviceService.get_device_by_no(device_no)
    if not device:
        return jsonify({"msg": "device not found"}), 404
    
    # 权限检查
    device_merchant_id = device.get('merchant_id')
    allowed_merchant_id = _merchant_filter(device_merchant_id, claims)
    if allowed_merchant_id and str(allowed_merchant_id) != str(device_merchant_id):
        return jsonify({"msg": "access denied"}), 403
    
    data = request.get_json(force=True) or {}
    
    # 可编辑字段
    update_data = {}
    for field in ["address", "address_detail", "summary_address", "scene", "customer_code"]:
        if field in data:
            update_data[field] = data[field]
    
    # 自定义字段（最多10个键）
    if "custom_fields" in data and isinstance(data["custom_fields"], dict):
        cf = data["custom_fields"]
        keys = list(cf.keys())[:10]
        update_data["custom_fields"] = {k: cf[k] for k in keys}
    
    if update_data:
        device_id = device.get('device_id')
        success = DeviceService.update_device(device_id, update_data)
        if success:
            return jsonify({"msg": "updated"})
        else:
            return jsonify({"msg": "update failed"}), 500
    
    return jsonify({"msg": "no changes"})


@bp.route("/api/devices/redis/commands", methods=["POST"])
@jwt_required(optional=True)
def batch_commands():
    """批量设备命令（Redis版本）"""
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    
    data: Dict[str, Any] = request.get_json(force=True) or {}
    device_nos = data.get("device_nos") or []
    device_ids = data.get("device_ids") or []
    command_type = data.get("command_type")
    payload = data.get("payload", {})
    
    if not device_nos and device_ids:
        # 将device_ids转换为device_nos
        device_nos = []
        for device_id in device_ids:
            device = DeviceService.get_device_by_id(str(device_id))
            if device:
                device_nos.append(device.get('device_no'))
    
    if not device_nos or not command_type:
        return jsonify({"msg": "device_nos 与 command_type 必填"}), 400
    
    batch_id = str(uuid.uuid4())
    issued = 0
    user_id = claims.get('id')
    
    for device_no in device_nos:
        device = DeviceService.get_device_by_no(device_no)
        if not device:
            continue
        
        # 权限检查
        device_merchant_id = device.get('merchant_id')
        allowed_merchant_id = _merchant_filter(device_merchant_id, claims)
        if allowed_merchant_id and str(allowed_merchant_id) != str(device_merchant_id):
            continue
        
        # 创建命令
        device_id = device.get('device_id')
        if device_id:
            command_payload = payload.copy()
            command_payload['batch_id'] = batch_id
            
            DeviceService.create_device_command(
                device_id, 
                command_type, 
                command_payload, 
                user_id
            )
            issued += 1
    
    return jsonify({"msg": f"已下发到 {issued} 台设备", "batch_id": batch_id})


@bp.route("/api/devices/redis/<int:device_id>/materials")
@jwt_required(optional=True)
def device_materials(device_id: int):
    """获取设备物料信息（Redis版本）"""
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    
    device = DeviceService.get_device_by_id(str(device_id))
    if not device:
        return jsonify({"msg": "device not found"}), 404
    
    # 权限检查
    device_merchant_id = device.get('merchant_id')
    allowed_merchant_id = _merchant_filter(device_merchant_id, claims)
    if allowed_merchant_id and str(allowed_merchant_id) != str(device_merchant_id):
        return jsonify({"msg": "access denied"}), 403
    
    materials = DeviceService.get_device_materials(str(device_id))
    
    return jsonify({
        "device_no": device.get('device_no'),
        "materials": materials
    })


@bp.route("/api/devices/redis/<int:device_id>/charts/series")
@jwt_required(optional=True)
def device_charts_series(device_id: int):
    """获取设备时间序列图表数据（Redis版本）"""
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    
    device = DeviceService.get_device_by_id(str(device_id))
    if not device:
        return jsonify({"msg": "device not found"}), 404
    
    # 权限检查
    device_merchant_id = device.get('merchant_id')  
    allowed_merchant_id = _merchant_filter(device_merchant_id, claims)
    if allowed_merchant_id and str(allowed_merchant_id) != str(device_merchant_id):
        return jsonify({"msg": "access denied"}), 403
    
    month = request.args.get("month")
    chart_data = DeviceStatsService.get_device_charts_data(str(device_id), "series", month)
    
    return jsonify(chart_data)


@bp.route("/api/devices/redis/<int:device_id>/charts/category_compare") 
@jwt_required(optional=True)
def device_charts_category(device_id: int):
    """获取设备分类对比图表数据（Redis版本）"""
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    
    device = DeviceService.get_device_by_id(str(device_id))
    if not device:
        return jsonify({"msg": "device not found"}), 404
    
    # 权限检查
    device_merchant_id = device.get('merchant_id')
    allowed_merchant_id = _merchant_filter(device_merchant_id, claims) 
    if allowed_merchant_id and str(allowed_merchant_id) != str(device_merchant_id):
        return jsonify({"msg": "access denied"}), 403
    
    chart_data = DeviceStatsService.get_device_charts_data(str(device_id), "category")
    
    return jsonify(chart_data)