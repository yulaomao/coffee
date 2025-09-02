"""物料管理 API：
- 兼容保留：
    - GET/PUT /api/devices/<id>/materials（基于旧 DeviceMaterial 模型）
    - GET /api/materials 与 /api/materials/export：返回设备-物料余量汇总列表（用于旧物料管理页）

- 新增（完整“物料与料盒管理”）：
    - 物料字典（Material Catalog）：
        - GET/POST /api/material_catalog
        - GET/PUT/DELETE /api/material_catalog/<id>
        - POST /api/material_catalog/import（CSV）
        - GET /api/material_catalog/export（CSV）
    - 设备料盒（Device Bins）：
        - GET/POST /api/devices/<int:device_id>/bins
        - PUT /api/devices/<int:device_id>/bins/<int:bin_index>/bind
        - PUT /api/devices/<int:device_id>/bins/<int:bin_index>/set_capacity
        - PUT /api/devices/<int:device_id>/bins/<int:bin_index>/set_label
        - POST /api/devices/bins/bulk_bind
        - GET /api/devices/bins/export
        - POST /api/devices/<int:device_id>/bins/<int:bin_index>/downlink（简化下发）

说明：管理页面支持会话回退，写操作需 RBAC 角色（merchant_admin/ops_engineer/superadmin）。
"""
from __future__ import annotations
from typing import Any, Optional
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import DeviceMaterial, Device, MaterialCatalog, User, OperationLog, DeviceBin, RemoteCommand
from ..extensions import db
from ..utils.security import merchant_scope_filter
from datetime import datetime
import csv
from io import StringIO

bp = Blueprint("materials", __name__)


@bp.route("/api/devices/<int:device_id>/materials", methods=["GET", "PUT"])
@jwt_required()
def device_materials(device_id: int):
    claims = get_jwt_identity() or {}
    # 设备维度物料需要基于设备的 merchant_id 进行过滤
    q = db.session.query(DeviceMaterial).join(Device, Device.id == DeviceMaterial.device_id)
    q = q.filter(DeviceMaterial.device_id == device_id)
    role = claims.get('role'); mid = claims.get('merchant_id')
    if role != 'superadmin' and mid is not None:
        q = q.filter(Device.merchant_id == int(mid))
    if request.method == "GET":
        items = q.all()
        fmt = request.args.get('format')
        if fmt == 'csv':
            from ..utils.helpers import csv_response
            rows = [[m.id, m.material_id, m.remain, getattr(m,'capacity',0), m.threshold] for m in items]
            return csv_response(["id","material_id","remain","capacity","threshold"], rows, filename=f"device_{device_id}_materials.csv")
        return jsonify({"items": [
            {"id": m.id, "material_id": m.material_id, "remain": m.remain, "capacity": getattr(m,'capacity',0), "threshold": m.threshold}
            for m in items
        ]})
    else:
        data: dict[str, Any] = request.get_json(force=True)
        for item in data.get("items", []):
            dm = DeviceMaterial.query.filter_by(device_id=device_id, material_id=item.get("material_id")).first()
            if dm:
                dm.threshold = float(item.get("threshold", dm.threshold))
                dm.remain = float(item.get("remain", dm.remain))
        db.session.commit()
        return jsonify({"msg": "updated"})


def _materials_base_query(claims):
    q = db.session.query(
        Device.device_no.label('device_no'),
        Device.model.label('device_name'),
        DeviceMaterial.material_id.label('bin_id'),
        MaterialCatalog.name.label('material_name'),
        MaterialCatalog.category.label('material_type'),
        DeviceMaterial.remain.label('remain'),
        DeviceMaterial.capacity.label('capacity'),
        DeviceMaterial.updated_at.label('updated_at'),
        MaterialCatalog.unit.label('unit'),
    ).select_from(DeviceMaterial)
    q = q.join(Device, Device.id == DeviceMaterial.device_id)
    q = q.outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceMaterial.material_id)
    # 使用设备的 merchant_id 进行过滤，superadmin 不限制
    try:
        role = claims.get('role') if claims else None
        mid = claims.get('merchant_id') if claims else None
        if role != 'superadmin' and mid is not None:
            q = q.filter(Device.merchant_id == int(mid))
    except Exception:
        pass
    return q


def _current_claims():
    """优先 JWT，若无则会话回退，返回 {id, role, merchant_id} 或 None。"""
    try:
        claims = get_jwt_identity()
    except Exception:
        claims = None
    if claims:
        return claims
    # session 回退
    from flask import session
    uid = session.get('user_id')
    if uid:
        u = User.query.get(uid)
        if u:
            return {"id": u.id, "role": u.role, "merchant_id": u.merchant_id}
    return None


def _require_write(claims) -> Optional[tuple[str,int]]:
    if not claims:
        return ("unauthorized", 401)
    role = claims.get('role')
    if role not in {"superadmin", "merchant_admin", "ops_engineer"}:
        return ("forbidden", 403)
    return None


# -------------------- 物料字典（Material Catalog） --------------------

@bp.route("/api/material_catalog", methods=["GET", "POST"])
@jwt_required(optional=True)
def material_catalog_list_create():
    claims = _current_claims()
    if request.method == "GET":
        q = MaterialCatalog.query
        # 筛选
        kw = request.args.get('name') or request.args.get('q')
        category = request.args.get('category')
        code = request.args.get('code')
        active = request.args.get('active')
        if kw:
            like = f"%{kw}%"; q = q.filter((MaterialCatalog.name.like(like)) | (MaterialCatalog.code.like(like)))
        if category:
            q = q.filter(MaterialCatalog.category == category)
        if code:
            q = q.filter(MaterialCatalog.code == code)
        if active is not None:
            if active.lower() in ("0","false","no"):
                q = q.filter(MaterialCatalog.is_active == False)  # noqa: E712
            elif active.lower() in ("1","true","yes"):
                q = q.filter(MaterialCatalog.is_active == True)  # noqa: E712
        page = int(request.args.get('page', 1)); per_page = min(int(request.args.get('per_page', 20)), 200)
        total = q.count()
        rows = q.order_by(MaterialCatalog.id.asc()).limit(per_page).offset((page-1)*per_page).all()
        return jsonify({"ok": True, "total": total, "page": page, "per_page": per_page, "items": [
            {
                "id": m.id, "code": m.code, "name": m.name, "category": m.category, "unit": m.unit,
                "default_capacity": m.default_capacity, "description": m.description, "is_active": m.is_active
            } for m in rows
        ]})
    # POST create
    err = _require_write(claims)
    if err: return jsonify({"ok": False, "message": err[0]}), err[1]
    data = request.get_json(force=True)
    m = MaterialCatalog(
        code=(data.get('code') or None),
        name=data['name'],
        category=data.get('category'),
        unit=data.get('unit') or 'g',
        default_capacity=data.get('default_capacity'),
        description=data.get('description'),
        created_by=claims.get('id') if claims else None,
        is_active=True,
    )
    db.session.add(m)
    db.session.commit()
    db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='material_create', target_type='material', target_id=m.id, ip=None, user_agent=None, raw_payload=data))
    db.session.commit()
    return jsonify({"ok": True, "data": {"id": m.id}})


@bp.route("/api/material_catalog/<int:mid>", methods=["GET", "PUT", "DELETE"])
@jwt_required(optional=True)
def material_catalog_detail(mid: int):
    claims = _current_claims()
    m = MaterialCatalog.query.get_or_404(mid)
    if request.method == "GET":
        return jsonify({"ok": True, "data": {
            "id": m.id, "code": m.code, "name": m.name, "category": m.category, "unit": m.unit,
            "default_capacity": m.default_capacity, "description": m.description, "is_active": m.is_active
        }})
    err = _require_write(claims)
    if err: return jsonify({"ok": False, "message": err[0]}), err[1]
    if request.method == "PUT":
        data = request.get_json(force=True)
        for f in ["code","name","category","unit","default_capacity","description","is_active"]:
            if f in data:
                setattr(m, f, data[f])
        db.session.commit()
        db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='material_update', target_type='material', target_id=m.id, ip=None, user_agent=None, raw_payload=data))
        db.session.commit()
        return jsonify({"ok": True})
    # DELETE -> 软删除
    m.is_active = False
    db.session.commit()
    db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='material_delete', target_type='material', target_id=m.id, ip=None, user_agent=None, raw_payload=None))
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/api/material_catalog/import", methods=["POST"])
@jwt_required(optional=True)
def material_catalog_import():
    claims = _current_claims()
    err = _require_write(claims)
    if err: return jsonify({"ok": False, "message": err[0]}), err[1]
    if 'file' not in request.files:
        return jsonify({"ok": False, "message": "missing file"}), 400
    f = request.files['file']
    content = f.read().decode('utf-8', errors='ignore')
    reader = csv.DictReader(StringIO(content))
    total = 0; inserted = 0; updated = 0; errors = []
    for row in reader:
        total += 1
        try:
            code = (row.get('code') or '').strip() or None
            name = (row.get('name') or '').strip()
            if not name:
                raise ValueError('name required')
            m = None
            if code:
                m = MaterialCatalog.query.filter_by(code=code).first()
            if not m:
                m = MaterialCatalog.query.filter_by(name=name).first()
            if m:
                m.code = code or m.code
                m.name = name or m.name
                m.category = (row.get('category') or m.category)
                m.unit = (row.get('unit') or m.unit or 'g')
                m.default_capacity = float(row.get('default_capacity')) if (row.get('default_capacity') or '').strip() else m.default_capacity
                m.description = (row.get('description') or m.description)
                m.is_active = True
                updated += 1
            else:
                db.session.add(MaterialCatalog(
                    code=code,
                    name=name,
                    category=(row.get('category') or None),
                    unit=(row.get('unit') or 'g'),
                    default_capacity=(float(row.get('default_capacity')) if (row.get('default_capacity') or '').strip() else None),
                    description=(row.get('description') or None),
                    created_by=claims.get('id') if claims else None,
                    is_active=True,
                ))
                inserted += 1
        except Exception as e:
            errors.append(f"line{total}:{e}")
    db.session.commit()
    from ..models import MaterialImportLog
    db.session.add(MaterialImportLog(user_id=claims.get('id') if claims else None, filename=getattr(f,'filename','import.csv'), total=total, inserted=inserted, updated=updated, errors='\n'.join(errors)))
    db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='material_import', target_type='material', target_id=None, ip=None, user_agent=None, raw_payload={"total": total, "inserted": inserted, "updated": updated, "errors": len(errors)}))
    db.session.commit()
    return jsonify({"ok": True, "data": {"total": total, "inserted": inserted, "updated": updated, "errors": errors}})


@bp.route("/api/material_catalog/export")
@jwt_required(optional=True)
def material_catalog_export():
    claims = _current_claims()
    q = MaterialCatalog.query.order_by(MaterialCatalog.id.asc())
    rows = q.all()
    from ..utils.helpers import csv_response
    csv_rows = [[m.code or '', m.name, (m.category or ''), m.unit or 'g', (m.default_capacity or ''), (m.description or ''), ('1' if m.is_active else '0')] for m in rows]
    # 审计
    try:
        db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='export', target_type='material_catalog', target_id=None, ip=None, user_agent=None))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return csv_response(["code","name","category","unit","default_capacity","description","is_active"], csv_rows, filename="material_catalog.csv")


# -------------------- 设备料盒（Device Bins） --------------------

def _get_or_create_bin(device_id: int, bin_index: int) -> DeviceBin:
    b = DeviceBin.query.filter_by(device_id=device_id, bin_index=bin_index).first()
    if not b:
        b = DeviceBin(device_id=device_id, bin_index=bin_index)
        db.session.add(b)
        db.session.flush()
    return b


@bp.route("/api/devices/<int:device_id>/bins", methods=["GET", "POST"])
@jwt_required(optional=True)
def device_bins(device_id: int):
    claims = _current_claims()
    if request.method == "GET":
        rows = db.session.query(DeviceBin, MaterialCatalog, Device).join(Device, Device.id == DeviceBin.device_id).outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceBin.material_id).filter(DeviceBin.device_id == device_id).all()
        res = []
        for b, m, d in rows:
            cap = b.capacity if b.capacity is not None else (m.default_capacity if m else None)
            res.append({
                "device_id": device_id,
                "bin_index": b.bin_index,
                "material": ({"id": m.id, "code": m.code, "name": m.name, "unit": m.unit} if m else None),
                "capacity": cap,
                "remaining": b.remaining,
                "unit": b.unit or (m.unit if m else None),
                "last_sync_at": (b.last_sync_at.isoformat() if b.last_sync_at else None),
                "custom_label": b.custom_label,
            })
        return jsonify(res)
    # POST: 初始化 bins
    err = _require_write(claims)
    if err: return jsonify({"ok": False, "message": err[0]}), err[1]
    data = request.get_json(force=True)
    bins = data.get('bins') or []
    for it in bins:
        idx = int(it.get('bin_index'))
        b = _get_or_create_bin(device_id, idx)
        if it.get('capacity') is not None:
            b.capacity = float(it.get('capacity'))
        if it.get('custom_label') is not None:
            b.custom_label = it.get('custom_label')
    db.session.commit()
    db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='device_bins_init', target_type='device', target_id=device_id, ip=None, user_agent=None, raw_payload={"bins": bins}))
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/api/devices/<int:device_id>/bins/<int:bin_index>/bind", methods=["PUT"])
@jwt_required(optional=True)
def device_bin_bind(device_id: int, bin_index: int):
    claims = _current_claims()
    err = _require_write(claims)
    if err: return jsonify({"ok": False, "message": err[0]}), err[1]
    data = request.get_json(force=True)
    material_id = data.get('material_id'); material_code = data.get('material_code')
    m = None
    if material_id:
        m = MaterialCatalog.query.get(material_id)
    elif material_code:
        m = MaterialCatalog.query.filter_by(code=material_code).first()
    if not m:
        return jsonify({"ok": False, "message": "material not found"}), 404
    b = _get_or_create_bin(device_id, bin_index)
    # 单位校验：默认以物料单位覆盖 bin.unit
    if b.unit and b.unit != m.unit:
        # 简化策略：覆盖并提示
        pass
    b.material_id = m.id
    b.unit = m.unit
    # 若 bin 未设置容量，则采用物料默认容量
    if b.capacity is None and m.default_capacity is not None:
        b.capacity = m.default_capacity
    db.session.commit()
    # 可选同步
    if data.get('sync'):
        # 简化下发：生成 RemoteCommand 记录
        payload = {"type": "bind", "bin_index": bin_index, "material_id": m.id, "material_code": m.code}
        cmd = RemoteCommand(
            command_id=f"BIN-{device_id}-{bin_index}-{int(datetime.utcnow().timestamp())}",
            device_id=device_id,
            command_type='config_bin',
            payload=payload,
            issued_by=(claims.get('id') if claims else 1),
            status='pending'
        )
        db.session.add(cmd); db.session.commit()
        status = 'sent' if (Device.query.get(device_id).status == 'online') else 'queued'
        db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='device_bind', target_type='device_bin', target_id=b.id, ip=None, user_agent=None, raw_payload={"bin_index": bin_index, "material_id": m.id, "sync": True, "status": status}))
        db.session.commit()
        return jsonify({"ok": True, "message": ("已下发" if status=='sent' else "已入队"), "command_id": cmd.command_id})
    db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='device_bind', target_type='device_bin', target_id=b.id, ip=None, user_agent=None, raw_payload={"bin_index": bin_index, "material_id": m.id, "sync": False}))
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/api/devices/<int:device_id>/bins/<int:bin_index>/set_capacity", methods=["PUT"])
@jwt_required(optional=True)
def device_bin_set_capacity(device_id: int, bin_index: int):
    claims = _current_claims()
    err = _require_write(claims)
    if err: return jsonify({"ok": False, "message": err[0]}), err[1]
    data = request.get_json(force=True)
    cap = data.get('capacity')
    if cap is None or float(cap) <= 0:
        return jsonify({"ok": False, "message": "capacity must > 0"}), 400
    b = _get_or_create_bin(device_id, bin_index)
    b.capacity = float(cap)
    db.session.commit()
    db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='device_set_capacity', target_type='device_bin', target_id=b.id, ip=None, user_agent=None, raw_payload={"bin_index": bin_index, "capacity": b.capacity}))
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/api/devices/<int:device_id>/bins/<int:bin_index>/set_label", methods=["PUT"])
@jwt_required(optional=True)
def device_bin_set_label(device_id: int, bin_index: int):
    claims = _current_claims()
    err = _require_write(claims)
    if err: return jsonify({"ok": False, "message": err[0]}), err[1]
    data = request.get_json(force=True)
    label = (data.get('custom_label') or '').strip()
    b = _get_or_create_bin(device_id, bin_index)
    b.custom_label = label
    db.session.commit()
    db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='device_set_label', target_type='device_bin', target_id=b.id, ip=None, user_agent=None, raw_payload={"bin_index": bin_index, "custom_label": label}))
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/api/devices/bins/bulk_bind", methods=["POST"])
@jwt_required(optional=True)
def device_bins_bulk_bind():
    claims = _current_claims()
    err = _require_write(claims)
    if err: return jsonify({"ok": False, "message": err[0]}), err[1]
    data = request.get_json(force=True)
    items = data.get('items') or []
    ok = 0; fail = 0; details = []
    for it in items:
        try:
            device_id = it.get('device_id')
            if not device_id and it.get('device_no'):
                d = Device.query.filter_by(device_no=it.get('device_no')).first()
                device_id = d.id if d else None
            bin_index = int(it.get('bin_index'))
            if not device_id:
                raise ValueError('device not found')
            m = None
            if it.get('material_id'):
                m = MaterialCatalog.query.get(it.get('material_id'))
            elif it.get('material_code'):
                m = MaterialCatalog.query.filter_by(code=it.get('material_code')).first()
            if not m:
                raise ValueError('material not found')
            b = _get_or_create_bin(int(device_id), bin_index)
            b.material_id = m.id; b.unit = m.unit
            if it.get('capacity') is not None:
                b.capacity = float(it.get('capacity'))
            if it.get('custom_label') is not None:
                b.custom_label = it.get('custom_label')
            ok += 1
            details.append({"device_id": int(device_id), "bin_index": bin_index, "material_id": m.id, "status": "ok"})
        except Exception as e:
            fail += 1
            details.append({"input": it, "error": str(e)})
    db.session.commit()
    db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='device_bulk_bind', target_type='device_bin', target_id=None, ip=None, user_agent=None, raw_payload={"ok": ok, "fail": fail}))
    db.session.commit()
    return jsonify({"ok": True, "data": {"ok": ok, "fail": fail, "details": details}})


@bp.route("/api/devices/bins/export")
@jwt_required(optional=True)
def device_bins_export():
    claims = _current_claims()
    q = db.session.query(Device, DeviceBin, MaterialCatalog).join(DeviceBin, Device.id == DeviceBin.device_id).outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceBin.material_id)
    device_id = request.args.get('device_id'); material_id = request.args.get('material_id'); threshold_pct = request.args.get('threshold')
    if device_id:
        q = q.filter(Device.id == int(device_id))
    if material_id:
        q = q.filter(DeviceBin.material_id == int(material_id))
    rows = q.order_by(Device.device_no.asc(), DeviceBin.bin_index.asc()).all()
    from ..utils.helpers import csv_response
    csv_rows = []
    for d, b, m in rows:
        cap = float(b.capacity or (m.default_capacity or 0) or 0)
        rem = float(b.remaining or 0)
        pct = (rem/cap*100) if cap>0 else 0
        csv_rows.append([d.device_no, b.bin_index, (m.code if m else ''), (m.name if m else ''), cap, rem, (b.unit or (m.unit if m else '')), b.custom_label or '', round(pct,1), (b.last_sync_at.isoformat() if b.last_sync_at else '')])
    # 阈值筛选（导出后筛）
    if threshold_pct:
        try:
            th = float(threshold_pct)
            csv_rows = [r for r in csv_rows if (float(r[8]) <= th)]
        except Exception:
            pass
    # 审计
    try:
        db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='export', target_type='device_bins', target_id=None, ip=None, user_agent=None))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return csv_response(["device_no","bin_index","material_code","material_name","capacity","remaining","unit","custom_label","percent","last_sync_at"], csv_rows, filename="device_bins.csv")


@bp.route("/api/devices/<int:device_id>/bins/<int:bin_index>/downlink", methods=["POST"])
@jwt_required(optional=True)
def device_bin_downlink(device_id: int, bin_index: int):
    claims = _current_claims()
    err = _require_write(claims)
    if err: return jsonify({"ok": False, "message": err[0]}), err[1]
    b = DeviceBin.query.filter_by(device_id=device_id, bin_index=bin_index).first()
    if not b:
        return jsonify({"ok": False, "message": "bin not found"}), 404
    payload = {"type": "sync_bin", "bin_index": bin_index, "material_id": b.material_id, "capacity": b.capacity, "unit": b.unit}
    cmd = RemoteCommand(
        command_id=f"BIN-SYNC-{device_id}-{bin_index}-{int(datetime.utcnow().timestamp())}",
        device_id=device_id,
        command_type='config_bin',
        payload=payload,
        issued_by=(claims.get('id') if claims else 1),
        status='pending'
    )
    db.session.add(cmd)
    db.session.commit()
    status = 'sent' if (Device.query.get(device_id).status == 'online') else 'queued'
    db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='device_bin_downlink', target_type='device_bin', target_id=b.id, ip=None, user_agent=None, raw_payload={"status": status}))
    db.session.commit()
    return jsonify({"ok": True, "message": ("已下发" if status=='sent' else "已入队"), "command_id": cmd.command_id})


@bp.route("/api/devices/bins/bulk_bind_csv", methods=["POST"])
@jwt_required(optional=True)
def device_bins_bulk_bind_csv():
    claims = _current_claims()
    err = _require_write(claims)
    if err: return jsonify({"ok": False, "message": err[0]}), err[1]
    if 'file' not in request.files:
        return jsonify({"ok": False, "message": "missing file"}), 400
    f = request.files['file']
    content = f.read().decode('utf-8', errors='ignore')
    reader = csv.DictReader(StringIO(content))
    ok = 0; fail = 0; details = []
    for row in reader:
        try:
            device_no = (row.get('device_no') or '').strip()
            d = Device.query.filter_by(device_no=device_no).first()
            if not d:
                raise ValueError('device not found')
            bin_index = int(row.get('bin_index'))
            m = None
            if row.get('material_code'):
                m = MaterialCatalog.query.filter_by(code=row.get('material_code').strip()).first()
            if not m:
                raise ValueError('material not found')
            b = _get_or_create_bin(d.id, bin_index)
            b.material_id = m.id; b.unit = m.unit
            if (row.get('capacity') or '').strip():
                b.capacity = float(row.get('capacity'))
            if row.get('custom_label') is not None:
                b.custom_label = row.get('custom_label')
            ok += 1; details.append({"device_no": device_no, "bin_index": bin_index, "material_code": m.code, "status": "ok"})
        except Exception as e:
            fail += 1; details.append({"row": row, "error": str(e)})
    db.session.commit()
    db.session.add(OperationLog(user_id=claims.get('id') if claims else None, action='device_bulk_bind', target_type='device_bin', target_id=None, ip=None, user_agent=None, raw_payload={"ok": ok, "fail": fail}))
    db.session.commit()
    return jsonify({"ok": True, "data": {"ok": ok, "fail": fail, "details": details}})


@bp.route("/api/materials")
@jwt_required(optional=True)
def materials_list():
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    q = _materials_base_query(claims)
    # 筛选
    device_no = request.args.get('device_id') or request.args.get('device_no')
    mtype = request.args.get('type')
    name = request.args.get('name')
    if device_no:
        q = q.filter(Device.device_no.like(f"%{device_no}%"))
    if mtype:
        q = q.filter((MaterialCatalog.category == mtype) | (MaterialCatalog.name == mtype))
    if name:
        like = f"%{name}%"; q = q.filter((MaterialCatalog.name.like(like)) | (Device.model.like(like)))
    page = int(request.args.get('page', 1)); per_page = min(int(request.args.get('per_page', 20)), 200)
    total = q.count()
    rows = q.order_by(Device.device_no.asc(), DeviceMaterial.material_id.asc()).limit(per_page).offset((page-1)*per_page).all()
    items = []
    for r in rows:
        cap = float(r.capacity or 0); rem = float(r.remain or 0); pct = (rem/cap*100) if cap>0 else 0
        items.append({
            "device_no": r.device_no,
            "device_name": r.device_name,
            "bin_id": r.bin_id,
            "material_name": r.material_name or f"料盒{r.bin_id}",
            "material_type": r.material_type or '-',
            "remain": rem,
            "capacity": cap,
            "percent": round(pct, 1),
            "unit": r.unit or 'g',
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return jsonify({"total": total, "page": page, "per_page": per_page, "items": items})


@bp.route("/api/materials/export")
@jwt_required(optional=True)
def materials_export():
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    q = _materials_base_query(claims)
    device_no = request.args.get('device_id') or request.args.get('device_no')
    mtype = request.args.get('type')
    name = request.args.get('name')
    if device_no:
        q = q.filter(Device.device_no.like(f"%{device_no}%"))
    if mtype:
        q = q.filter((MaterialCatalog.category == mtype) | (MaterialCatalog.name == mtype))
    if name:
        like = f"%{name}%"; q = q.filter((MaterialCatalog.name.like(like)) | (Device.model.like(like)))
    rows = q.order_by(Device.device_no.asc(), DeviceMaterial.material_id.asc()).all()
    from ..utils.helpers import csv_response
    csv_rows = []
    for r in rows:
        cap = float(r.capacity or 0); rem = float(r.remain or 0); pct = (rem/cap*100) if cap>0 else 0
        csv_rows.append([r.device_no, r.device_name, r.bin_id, r.material_name or f"料盒{r.bin_id}", r.material_type or '-', rem, cap, round(pct,1), r.unit or 'g', r.updated_at.isoformat() if r.updated_at else ''])
    # 导出审计
    try:
        db.session.add(OperationLog(user_id=claims.get('id'), action='export', target_type='materials', target_id=None, ip=None, user_agent=None))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return csv_response(["device_no","device_name","bin_id","material_name","material_type","remain","capacity","percent","unit","updated_at"], csv_rows, filename="materials.csv")
