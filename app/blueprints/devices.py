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
from ..models import Device, Order, RemoteCommand, CommandResult, Merchant, DeviceMaterial, User, CleaningLog, OperationLog, MaterialCatalog
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


# ========== 顶部状态与参数 ==========
@bp.route("/api/devices/<int:device_id>/summary")
@jwt_required(optional=True)
def device_summary(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    q = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims)
    d = q.first_or_404()
    # 简化：根据是否有未解决故障/低料判断
    fault_status = "normal"  # TODO: 故障模型细化后完善
    material_status = "normal"
    last_sync_at = d.updated_at.isoformat() if getattr(d, 'updated_at', None) else None
    return jsonify({
        "device_id": d.id,
        "device_no": d.device_no,
        "online": d.status == "online",
        "fault_status": fault_status,
        "material_status": material_status,
        "last_sync_at": last_sync_at,
    })


@bp.route("/api/devices/<int:device_id>/params")
@jwt_required(optional=True)
def device_params(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    return jsonify({
        "device_id": d.id,
        "device_no": d.device_no,
        "model": d.model,
        "firmware_version": d.firmware_version,
        "address": d.address,
        "address_detail": getattr(d, 'address_detail', None),
        "summary_address": getattr(d, 'summary_address', None),
        "scene": getattr(d, 'scene', None),
        "customer_code": getattr(d, 'customer_code', None),
        "custom_fields": d.custom_fields or {},
        "merchant_id": d.merchant_id,
    })


@bp.route("/api/devices/<int:device_id>/sync_state", methods=["POST"])
@jwt_required(optional=True)
def device_sync_state(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    # 这里触发模拟任务：异步拉取状态（队列）
    task_id = str(uuid.uuid4())
    submit_task(Task(id=task_id, type="sync_state", payload={"device_id": d.id}))
    # 审计
    try:
        db.session.add(OperationLog(user_id=claims.get('id'), action='sync_state', target_type='device', target_id=d.id, ip=None, user_agent=None))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify({"ok": True, "message": "同步触发", "request_id": task_id, "status": "queued"})


# ========== 物料区 ==========
@bp.route("/api/devices/<int:device_id>/materials")
@jwt_required(optional=True)
def device_materials(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    rows = (
        db.session.query(
            DeviceMaterial.material_id.label('bin_id'),
            DeviceMaterial.remain, DeviceMaterial.capacity, DeviceMaterial.updated_at,
            MaterialCatalog.name.label('material_name'),
            MaterialCatalog.unit.label('unit'),
            MaterialCatalog.category.label('category'),
        )
        .select_from(DeviceMaterial)
        .outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceMaterial.material_id)
        .filter(DeviceMaterial.device_id == d.id)
        .order_by(DeviceMaterial.material_id.asc())
        .all()
    )
    items = []
    for r in rows:
        items.append({
            "bin_id": r.bin_id,
            "name": (r.material_name or f"料盒{r.bin_id}"),
            "remain": float(r.remain or 0),
            "capacity": float(getattr(r, 'capacity', 100) or 100),
            "unit": (r.unit or 'g'),
            "material_type": r.category or '-',
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return jsonify(items)


@bp.route("/api/devices/<int:device_id>/materials/<int:bin_id>/capacity", methods=["PATCH"])
@jwt_required(optional=True)
def device_material_capacity(device_id: int, bin_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    dm = DeviceMaterial.query.filter_by(device_id=d.id, material_id=bin_id).first()
    if not dm:
        return jsonify({"ok": False, "message": "未找到料盒"}), 404
    # 版本限制：示例里仅提示
    data = request.get_json(force=True) or {}
    new_cap = float(data.get("capacity", 0))
    dm.capacity = new_cap
    db.session.commit()
    try:
        db.session.add(OperationLog(user_id=claims.get('id'), action='set_capacity', target_type='device_material', target_id=dm.id, ip=None, user_agent=None))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify({"ok": True, "message": "容量已更新（可能受版本限制）"})


@bp.route("/api/devices/<int:device_id>/materials/<int:bin_id>/fill", methods=["POST"])
@jwt_required(optional=True)
def device_material_fill(device_id: int, bin_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    dm = DeviceMaterial.query.filter_by(device_id=d.id, material_id=bin_id).first()
    if not dm:
        return jsonify({"ok": False, "message": "未找到料盒"}), 404
    task_id = str(uuid.uuid4())
    submit_task(Task(id=task_id, type="material_fill", payload={"device_id": d.id, "bin_id": bin_id}))
    try:
        db.session.add(OperationLog(user_id=claims.get('id'), action='material_fill', target_type='device_material', target_id=dm.id, ip=None, user_agent=None))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify({"ok": True, "message": "指令已下发（受版本限制）", "request_id": task_id, "status": "queued"})


@bp.route("/api/devices/<int:device_id>/materials/export")
@jwt_required(optional=True)
def device_materials_export(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    rows = (
        db.session.query(
            DeviceMaterial.material_id.label('bin_id'),
            DeviceMaterial.remain, DeviceMaterial.capacity, DeviceMaterial.updated_at,
            MaterialCatalog.name.label('material_name'),
            MaterialCatalog.unit.label('unit'),
            MaterialCatalog.category.label('category'),
        )
        .select_from(DeviceMaterial)
        .outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceMaterial.material_id)
        .filter(DeviceMaterial.device_id == d.id)
        .order_by(DeviceMaterial.material_id.asc())
        .all()
    )
    from ..utils.helpers import csv_response
    csv_rows = []
    for r in rows:
        csv_rows.append([
            r.bin_id,
            (r.material_name or f"料盒{r.bin_id}"),
            float(r.remain or 0),
            float(getattr(r, 'capacity', 100) or 100),
            (r.unit or 'g'),
            r.updated_at.isoformat() if r.updated_at else '',
        ])
    try:
        db.session.add(OperationLog(user_id=claims.get('id'), action='export', target_type='materials', target_id=d.id, ip=None, user_agent=None))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return csv_response(["bin_id","name","remain","capacity","unit","updated_at"], csv_rows, filename=f"device_{d.device_no}_materials.csv")


# ========== 订单（按月） ==========
def _month_range(month: str | None):
    from datetime import datetime, timedelta
    if not month:
        base = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        base = datetime.strptime(month + "-01", "%Y-%m-%d")
    end = (base.replace(day=28) + timedelta(days=4)).replace(day=1)
    return base, end


@bp.route("/api/devices/<int:device_id>/orders")
@jwt_required(optional=True)
def device_orders_month(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    month = request.args.get("month")
    view = request.args.get("view", "amount")  # amount|count|category
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    start, end = _month_range(month)
    q = Order.query.filter(Order.device_id == d.id, Order.created_at >= start, Order.created_at < end)
    q_paid = q.filter(Order.pay_status == "paid")
    items = q.order_by(Order.created_at.desc()).all()
    result_items = [{
        "order_no": o.order_no,
        "created_at": o.created_at.isoformat(),
        "product_name": o.product_name,
        "qty": int(o.qty or 1),
        "total_amount": float(o.total_amount or 0),
        "pay_method": o.pay_method,
        "pay_status": o.pay_status,
    } for o in items]
    if view == "count":
        summary = {"count": q_paid.count()}
    elif view == "category":
        rows = db.session.query(Order.product_name, db.func.count(Order.id)).filter(q_paid.whereclause).group_by(Order.product_name).all()
        summary = {"by_category": [{"k": r[0] or "-", "v": int(r[1])} for r in rows]}
    else:
        amt = db.session.query(db.func.coalesce(db.func.sum(Order.total_amount), 0)).filter(q_paid.whereclause).scalar() or 0
        summary = {"amount": float(amt)}
    return jsonify({"items": result_items, "summary": summary, "month": (month or start.strftime("%Y-%m"))})


@bp.route("/api/devices/<int:device_id>/orders/export")
@jwt_required(optional=True)
def device_orders_export(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    month = request.args.get("month")
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    start, end = _month_range(month)
    q = Order.query.filter(Order.device_id == d.id, Order.created_at >= start, Order.created_at < end)
    items = q.order_by(Order.created_at.desc()).all()
    from ..utils.helpers import csv_response
    rows = [[o.order_no or '', o.created_at.isoformat(), o.product_name or '', int(o.qty or 1), str(o.total_amount or 0), o.pay_method, o.pay_status] for o in items]
    try:
        db.session.add(OperationLog(user_id=claims.get('id'), action='export', target_type='orders_device', target_id=d.id, ip=None, user_agent=None))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return csv_response(["order_no","created_at","product_name","qty","total_amount","pay_method","pay_status"], rows, filename=f"device_{d.device_no}_{(month or start.strftime('%Y-%m'))}_orders.csv")


# ========== 清洗日志 ==========
@bp.route("/api/devices/<int:device_id>/cleaning")
@jwt_required(optional=True)
def device_cleaning(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    # 简化：默认支持；如要限制可返回 501
    from_s = request.args.get("from")
    to_s = request.args.get("to")
    typ = request.args.get("type")
    q = CleaningLog.query.filter(CleaningLog.device_id == device_id)
    if from_s:
        try:
            from datetime import datetime
            q = q.filter(CleaningLog.created_at >= datetime.fromisoformat(from_s))
        except Exception:
            pass
    if to_s:
        try:
            from datetime import datetime, timedelta
            q = q.filter(CleaningLog.created_at < datetime.fromisoformat(to_s) + timedelta(days=1))
        except Exception:
            pass
    if typ:
        q = q.filter(CleaningLog.type == typ)
    items = q.order_by(CleaningLog.created_at.desc()).limit(500).all()
    return jsonify([{
        "created_at": c.created_at.isoformat(),
        "type": c.type,
        "result": c.result,
        "duration_ms": c.duration_ms,
        "note": c.note,
    } for c in items])


@bp.route("/api/devices/<int:device_id>/cleaning/export")
@jwt_required(optional=True)
def device_cleaning_export(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    q = CleaningLog.query.filter(CleaningLog.device_id == device_id).order_by(CleaningLog.created_at.desc())
    items = q.all()
    from ..utils.helpers import csv_response
    rows = [[c.created_at.isoformat(), c.type, c.result, c.duration_ms, c.note or ''] for c in items]
    try:
        db.session.add(OperationLog(user_id=claims.get('id'), action='export', target_type='cleaning', target_id=device_id, ip=None, user_agent=None))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return csv_response(["created_at","type","result","duration_ms","note"], rows, filename=f"device_{device_id}_cleaning.csv")


# ========== 销售图表 ==========
@bp.route("/api/devices/<int:device_id>/charts/series")
@jwt_required(optional=True)
def device_charts_series(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    metric = request.args.get("metric", "amount")  # amount|count
    month = request.args.get("month")
    start, end = _month_range(month)
    q = Order.query.filter(Order.device_id == device_id, Order.created_at >= start, Order.created_at < end, Order.pay_status == "paid")
    from sqlalchemy import func
    k = func.strftime('%Y-%m-%d', Order.created_at)
    agg = func.sum(Order.total_amount) if metric == 'amount' else func.count(Order.id)
    rows = db.session.query(k.label('k'), agg.label('v')).select_from(Order).filter(q.whereclause).group_by('k').order_by('k').all()
    return jsonify([{"k": r[0], "v": float(r[1]) if r[1] is not None else 0} for r in rows])


@bp.route("/api/devices/<int:device_id>/charts/category_compare")
@jwt_required(optional=True)
def device_charts_category(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    metric = request.args.get("metric", "amount")
    month = request.args.get("month")
    start, end = _month_range(month)
    q = Order.query.filter(Order.device_id == device_id, Order.created_at >= start, Order.created_at < end, Order.pay_status == "paid")
    from sqlalchemy import func
    agg = func.sum(Order.total_amount) if metric == 'amount' else func.count(Order.id)
    rows = db.session.query(Order.product_name.label('k'), agg.label('v')).select_from(Order).filter(q.whereclause).group_by('k').order_by('k').all()
    return jsonify([{"k": r[0] or '-', "v": float(r[1]) if r[1] is not None else 0} for r in rows])


@bp.route("/api/devices/<int:device_id>/charts/export")
@jwt_required(optional=True)
def device_charts_export(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    typ = request.args.get("type", "series")
    month = request.args.get("month")
    metric = request.args.get("metric", "amount")
    if typ == 'category':
        data = device_charts_category.__wrapped__(device_id)  # type: ignore
    else:
        data = device_charts_series.__wrapped__(device_id)  # type: ignore
    # 审计
    try:
        db.session.add(OperationLog(user_id=claims.get('id'), action='export', target_type='charts', target_id=device_id, ip=None, user_agent=None))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return data


# ========== 远程操作/升级/参数 ==========
def _audit(op: str, target: str, target_id: int | None, claims: dict):
    try:
        db.session.add(OperationLog(user_id=claims.get('id'), action=op, target_type=target, target_id=target_id, ip=None, user_agent=None))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _passcode_ok(device_no: str, code: str) -> bool:
    last5 = device_no[-5:]
    return code == last5 or code == f"zhimakaimen{last5}" or code == "110"


@bp.route("/api/devices/<int:device_id>/command/open_door", methods=["POST"])
@jwt_required(optional=True)
def cmd_open_door(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    code = (request.get_json(silent=True) or {}).get("passcode", "")
    if not _passcode_ok(d.device_no, code):
        return jsonify({"ok": False, "message": "口令错误"}), 400
    cmd_id = str(uuid.uuid4())
    rc = RemoteCommand(command_id=cmd_id, device_id=d.id, command_type="open_door", payload={}, issued_by=claims.get('id'), status="pending")
    db.session.add(rc); db.session.commit()
    submit_task(Task(id=cmd_id, type="dispatch_command", payload={"command_id": cmd_id}))
    _audit('command_open_door', 'device', d.id, claims)
    return jsonify({"ok": True, "message": "指令已下发，是否成功以机端版本为准", "request_id": cmd_id, "status": "queued"})


@bp.route("/api/devices/<int:device_id>/command/reboot", methods=["POST"])
@jwt_required(optional=True)
def cmd_reboot(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    code = (request.get_json(silent=True) or {}).get("passcode", "")
    if not _passcode_ok(d.device_no, code):
        return jsonify({"ok": False, "message": "口令错误"}), 400
    cmd_id = str(uuid.uuid4())
    rc = RemoteCommand(command_id=cmd_id, device_id=d.id, command_type="reboot", payload={}, issued_by=claims.get('id'), status="pending")
    db.session.add(rc); db.session.commit()
    submit_task(Task(id=cmd_id, type="dispatch_command", payload={"command_id": cmd_id}))
    _audit('command_reboot', 'device', d.id, claims)
    return jsonify({"ok": True, "message": "指令已下发，是否成功以机端版本为准", "request_id": cmd_id, "status": "queued"})


@bp.route("/api/devices/<int:device_id>/command/make_product", methods=["POST"])
@jwt_required(optional=True)
def cmd_make_product(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    data = request.get_json(force=True) or {}
    pid = data.get("product_id")
    if not pid:
        return jsonify({"ok": False, "message": "缺少 product_id"}), 400
    cmd_id = str(uuid.uuid4())
    rc = RemoteCommand(command_id=cmd_id, device_id=d.id, command_type="make_product", payload={"product_id": pid}, issued_by=claims.get('id'), status="pending")
    db.session.add(rc); db.session.commit()
    submit_task(Task(id=cmd_id, type="dispatch_command", payload={"command_id": cmd_id}))
    _audit('command_make_product', 'device', d.id, claims)
    return jsonify({"ok": True, "message": "指令已下发，是否成功以机端版本为准", "request_id": cmd_id, "status": "queued"})


@bp.route("/api/devices/<int:device_id>/pricing/set_price", methods=["POST"])
@jwt_required(optional=True)
def cmd_set_price(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    data = request.get_json(force=True) or {}
    if not data.get("product_id") or data.get("new_price") is None:
        return jsonify({"ok": False, "message": "缺少 product_id/new_price"}), 400
    cmd_id = str(uuid.uuid4())
    rc = RemoteCommand(command_id=cmd_id, device_id=d.id, command_type="set_price", payload={"product_id": data["product_id"], "new_price": data["new_price"]}, issued_by=claims.get('id'), status="pending")
    db.session.add(rc); db.session.commit()
    submit_task(Task(id=cmd_id, type="dispatch_command", payload={"command_id": cmd_id}))
    _audit('pricing_set_price', 'device', d.id, claims)
    return jsonify({"ok": True, "message": "指令已下发，是否成功以机端版本为准", "request_id": cmd_id, "status": "queued"})


@bp.route("/api/devices/<int:device_id>/pricing/set_discount", methods=["POST"])
@jwt_required(optional=True)
def cmd_set_discount(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    data = request.get_json(force=True) or {}
    if data.get("discount_percent") is None:
        return jsonify({"ok": False, "message": "缺少 discount_percent"}), 400
    cmd_id = str(uuid.uuid4())
    rc = RemoteCommand(command_id=cmd_id, device_id=d.id, command_type="set_discount", payload={"discount_percent": data["discount_percent"]}, issued_by=claims.get('id'), status="pending")
    db.session.add(rc); db.session.commit()
    submit_task(Task(id=cmd_id, type="dispatch_command", payload={"command_id": cmd_id}))
    _audit('pricing_set_discount', 'device', d.id, claims)
    return jsonify({"ok": True, "message": "指令已下发，是否成功以机端版本为准", "request_id": cmd_id, "status": "queued"})


@bp.route("/api/devices/<int:device_id>/materials/set_remaining", methods=["POST"])
@jwt_required(optional=True)
def cmd_set_remaining(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    data = request.get_json(force=True) or {}
    if data.get("bin_id") is None or data.get("new_remaining") is None:
        return jsonify({"ok": False, "message": "缺少 bin_id/new_remaining"}), 400
    cmd_id = str(uuid.uuid4())
    rc = RemoteCommand(command_id=cmd_id, device_id=d.id, command_type="set_remaining", payload={"bin_id": data["bin_id"], "new_remaining": data["new_remaining"]}, issued_by=claims.get('id'), status="pending")
    db.session.add(rc); db.session.commit()
    submit_task(Task(id=cmd_id, type="dispatch_command", payload={"command_id": cmd_id}))
    _audit('material_set_remaining', 'device', d.id, claims)
    return jsonify({"ok": True, "message": "指令已下发，是否成功以机端版本为准", "request_id": cmd_id, "status": "queued"})


@bp.route("/api/devices/<int:device_id>/upgrade", methods=["POST"])
@jwt_required(optional=True)
def cmd_upgrade(device_id: int):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    d = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    data = request.get_json(force=True) or {}
    up_type = data.get("type")
    package_id = data.get("package_id")
    if up_type not in ("ad","recipe","software") or not package_id:
        return jsonify({"ok": False, "message": "参数错误"}), 400
    cmd_id = str(uuid.uuid4())
    rc = RemoteCommand(command_id=cmd_id, device_id=d.id, command_type=f"upgrade_{up_type}", payload={"package_id": package_id}, issued_by=claims.get('id'), status="pending")
    db.session.add(rc); db.session.commit()
    submit_task(Task(id=cmd_id, type="dispatch_command", payload={"command_id": cmd_id}))
    _audit(f'upgrade_{up_type}', 'device', d.id, claims)
    return jsonify({"ok": True, "message": "指令已下发，是否成功以机端版本为准", "request_id": cmd_id, "status": "queued"})


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


# ========== 新的客户端命令接口 ==========

@bp.route("/api/devices/<int:device_id>/client_command", methods=["POST"])
@jwt_required(optional=True)
def send_client_command(device_id: int):
    """
    向设备发送客户端命令 (新的ClientCommand接口)
    POST /api/devices/<device_id>/client_command
    
    Body: {
        "command_type": "make_coffee",
        "parameters": {"recipe": "espresso", "size": "medium"},
        "priority": 1,
        "timeout_seconds": 30
    }
    """
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
        
    device = merchant_scope_filter(Device.query.filter(Device.id == device_id), claims).first_or_404()
    data = request.get_json(force=True) or {}
    
    command_type = data.get("command_type")
    if not command_type:
        return jsonify({"error": "command_type is required"}), 400
    
    # 导入 ClientCommand 模型
    from ..models import ClientCommand
    
    # 创建命令
    command_id = str(uuid.uuid4())
    command = ClientCommand(
        command_id=command_id,
        device_id=device.id,
        command_type=command_type,
        parameters=data.get("parameters", {}),
        priority=data.get("priority", 0),
        timeout_seconds=data.get("timeout_seconds"),
        created_by=claims.get("id")
    )
    
    if data.get("timeout_seconds"):
        from datetime import timedelta
        command.expires_at = datetime.utcnow() + timedelta(seconds=data["timeout_seconds"])
    
    db.session.add(command)
    db.session.commit()
    
    # 记录操作日志
    try:
        db.session.add(OperationLog(
            user_id=claims.get('id', 0), 
            action='send_client_command', 
            target_type='device', 
            target_id=device.id, 
            raw_payload=data
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
    
    return jsonify({
        "ok": True,
        "message": "客户端命令已下发",
        "command_id": command_id,
        "status": "pending"
    })
