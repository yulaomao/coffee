"""设备管理 API（增强版）。
- GET /api/devices?search=&status=&merchant_id=&page=&per_page=&format=csv
- GET /api/devices/<device_no>
- POST /api/devices/commands { device_nos:[], command_type, payload }
- POST /api/devices/<device_no>/command_result
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from flask import Blueprint, jsonify, request, session
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..extensions import db
from ..models import Device, Order, RemoteCommand, CommandResult, Merchant, DeviceMaterial, User
from ..utils.security import merchant_scope_filter
from ..tasks.queue import Task, submit_task
from ..models import CustomFieldConfig

bp = Blueprint("devices", __name__)


def _current_claims():
    """优先使用 JWT 身份；若无，则回退到会话用户。

    返回形如 {id, role, merchant_id} 的 dict；若均不存在，返回 None。
    """
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
@bp.route("/api/devices/<string:device_no>", methods=["PATCH"])
@jwt_required(optional=True)
def update_device(device_no: str):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    device = merchant_scope_filter(Device.query.filter_by(device_no=device_no), claims).first_or_404()
    data = request.get_json(force=True) or {}
    # 可编辑字段
    for field in ["address", "address_detail", "summary_address", "scene", "customer_code"]:
        if field in data:
            setattr(device, field, data[field])
    # 自定义字段（最多10个键）
    if "custom_fields" in data and isinstance(data["custom_fields"], dict):
        cf = data["custom_fields"]
        # 限制最多10键
        keys = list(cf.keys())[:10]
        device.custom_fields = {k: cf[k] for k in keys}
    db.session.commit()
    return jsonify({"msg":"updated"})


@bp.route("/api/custom_field_config", methods=["GET","POST","PATCH"])
@jwt_required()
def custom_field_config():
    if request.method == "GET":
        items = CustomFieldConfig.query.order_by(CustomFieldConfig.key_index.asc()).all()
        return jsonify([{ "key_index":i.key_index, "enabled":i.enabled, "title":i.title } for i in items])
    data = request.get_json(force=True) or {}
    if request.method == "POST":
        # 初始化或替换配置
        CustomFieldConfig.query.delete()
        for i, item in enumerate(data.get("items", [])[:10], start=1):
            cfg = CustomFieldConfig(key_index=i, enabled=bool(item.get("enabled", True)), title=item.get("title") or f"字段{i}")
            db.session.add(cfg)
        db.session.commit()
        return jsonify({"msg":"saved"})
    # PATCH: 单个更新
    idx = int(data.get("key_index", 0))
    cfg = CustomFieldConfig.query.filter_by(key_index=idx).first()
    if not cfg:
        cfg = CustomFieldConfig(key_index=idx)
        db.session.add(cfg)
    if "enabled" in data: cfg.enabled = bool(data["enabled"]) 
    if "title" in data: cfg.title = data["title"]
    db.session.commit()
    return jsonify({"msg":"updated"})


@bp.route("/api/devices")
@jwt_required(optional=True)
def list_devices():
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    q = Device.query.join(Merchant, Merchant.id == Device.merchant_id)
    q = merchant_scope_filter(q, claims)
    # 过滤
    search = request.args.get("search")
    status = request.args.get("status")
    merchant_id = request.args.get("merchant_id")
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(Device.device_no.like(like), Device.model.like(like)))
    if status:
        q = q.filter(Device.status == status)
    if merchant_id:
        try:
            q = q.filter(Device.merchant_id == int(merchant_id))
        except Exception:
            pass

    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    fmt = request.args.get("format")
    total = q.count()
    items = q.order_by(Device.created_at.desc()).limit(per_page).offset((page - 1) * per_page).all()

    if fmt == "csv":
        from ..utils.helpers import csv_response
        rows = []
        for d in items:
            rows.append([
                d.device_no, d.model or "", d.status, d.last_seen.isoformat() if d.last_seen else "",
                getattr(d, 'address', '') or '', getattr(d, 'scene', '') or '', getattr(d, 'customer_code','') or ''
            ])
        return csv_response(["device_no","model","status","last_seen","address","scene","customer_code"], rows, filename="devices.csv")

    # 今日销量（仅统计已支付）
    start_today_dt = datetime.combine(datetime.utcnow().date(), datetime.min.time())
    sales_map = {
        r[0]: r[1]
        for r in db.session.query(Order.device_id, db.func.count(Order.id))
            .filter(Order.created_at >= start_today_dt, Order.pay_status == "paid")
            .group_by(Order.device_id)
            .all()
    }
    result_items = []
    for d in items:
        result_items.append({
            "device_no": d.device_no,
            "model": d.model,
            "status": d.status,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
            "location_lat": d.location_lat,
            "location_lng": d.location_lng,
            "merchant_name": d.merchant.name if d.merchant else None,
            "address": d.address,
            "scene": getattr(d, 'scene', None),
            "customer_code": getattr(d, 'customer_code', None),
            "custom_fields": d.custom_fields or {},
            "today_sales": int(sales_map.get(d.id, 0)),
        })
    return jsonify({"total": total, "page": page, "per_page": per_page, "items": result_items})


@bp.route("/api/devices/<string:device_no>")
@jwt_required(optional=True)
def device_detail(device_no: str):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    q = Device.query.filter_by(device_no=device_no)
    q = merchant_scope_filter(q, claims)
    device = q.first_or_404()
    materials = DeviceMaterial.query.filter_by(device_id=device.id).all()
    recent_orders = Order.query.filter_by(device_id=device.id).order_by(Order.created_at.desc()).limit(10).all()
    # 简单的命令历史（最近10条）
    from ..models import RemoteCommand
    cmds = RemoteCommand.query.filter_by(device_id=device.id).order_by(RemoteCommand.created_at.desc()).limit(10).all()
    return jsonify({
        "device": {
            "device_no": device.device_no,
            "model": device.model,
            "status": device.status,
            "last_seen": device.last_seen.isoformat() if device.last_seen else None,
            "firmware_version": device.firmware_version,
            "address": device.address,
            "address_detail": getattr(device, 'address_detail', None),
            "summary_address": getattr(device, 'summary_address', None),
            "scene": getattr(device, 'scene', None),
            "customer_code": getattr(device, 'customer_code', None),
            "custom_fields": device.custom_fields or {},
        },
        "materials": [{"material_id": m.material_id, "remain": float(m.remain), "capacity": float(getattr(m,'capacity',0)), "threshold": float(m.threshold)} for m in materials],
        "recent_orders": [
            {
                "id": o.id,
                "order_no": o.order_no,
                "product_name": o.product_name,
                "qty": int(getattr(o, "qty", 1) or 1),
                "total_amount": float(o.total_amount or 0),
                "pay_status": o.pay_status,
                "created_at": o.created_at.isoformat(),
            }
            for o in recent_orders
        ],
        "faults": [],
        "command_history": [{"command_id": c.command_id, "type": c.command_type, "status": c.status, "result_at": c.result_at.isoformat() if getattr(c,'result_at',None) else None} for c in cmds]
    })


@bp.route("/api/devices/commands", methods=["POST"])
@jwt_required(optional=True)
def batch_commands():
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    data: dict[str, Any] = request.get_json(force=True)
    device_nos = data.get("device_nos") or []
    # 兼容传入 device_ids
    device_ids = data.get("device_ids") or []
    if device_ids and not device_nos:
        found = Device.query.filter(Device.id.in_(device_ids)).all()
        device_nos = [d.device_no for d in found]
    command_type = data.get("command_type")
    payload = data.get("payload", {})
    if not device_nos or not command_type:
        return jsonify({"msg": "device_nos 与 command_type 必填"}), 400
    batch_id = str(uuid.uuid4())
    issued = 0
    for dno in device_nos:
        device = Device.query.filter_by(device_no=dno).first()
        if not device:
            continue
        # 多租户检查
        if claims.get("role") != "superadmin" and device.merchant_id != claims.get("merchant_id"):
            continue
        cmd_id = str(uuid.uuid4())
        rc = RemoteCommand(
            command_id=cmd_id,
            device_id=device.id,
            command_type=command_type,
            payload=payload,
            issued_by=claims.get("id"),
            status="pending",
            batch_info=batch_id,
        )
        db.session.add(rc)
        issued += 1
        submit_task(Task(id=cmd_id, type="dispatch_command", payload={"command_id": cmd_id}))
    db.session.commit()
    return jsonify({"command_batch_id": batch_id, "issued_count": issued})


@bp.route("/api/devices/<string:device_no>/command_result", methods=["POST"])
@jwt_required(optional=True)
def command_result(device_no: str):
    data: dict[str, Any] = request.get_json(force=True)
    command_id = data.get("command_id")
    status = data.get("status", "success")
    success = status == "success"
    message = data.get("message")
    raw = data
    if not command_id:
        return jsonify({"msg": "command_id 必填"}), 400
    device = Device.query.filter_by(device_no=device_no).first()
    if not device:
        return jsonify({"msg":"device not found"}), 404
    cr = CommandResult(command_id=command_id, device_id=device.id, success=success, message=message, raw_payload=raw)
    # 同步更新命令状态
    rc = RemoteCommand.query.filter_by(command_id=command_id, device_id=device.id).first()
    if rc:
        rc.status = "success" if success else "fail"
        rc.result_payload = raw
        rc.result_at = datetime.utcnow()
    db.session.add(cr)
    db.session.commit()
    return jsonify({"msg": "ok"})


@bp.route("/api/devices/export")
@jwt_required(optional=True)
def export_devices():
    # 复用 list_devices 过滤逻辑，但导出全量匹配结果
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    q = Device.query
    q = merchant_scope_filter(q, claims)
    search = request.args.get("search")
    status = request.args.get("status")
    merchant_id = request.args.get("merchant_id")
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(Device.device_no.like(like), Device.model.like(like)))
    if status:
        q = q.filter(Device.status == status)
    if merchant_id:
        try:
            q = q.filter(Device.merchant_id == int(merchant_id))
        except Exception:
            pass
    items = q.order_by(Device.created_at.desc()).all()
    from ..utils.helpers import csv_response
    rows = [[d.device_no, d.model or '', d.status, d.last_seen.isoformat() if d.last_seen else '', d.address or ''] for d in items]
    return csv_response(["device_no","model","status","last_seen","address"], rows, filename="devices_export.csv")
