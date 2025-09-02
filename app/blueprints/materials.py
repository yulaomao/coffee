"""物料管理 API：
- GET /api/devices/<id>/materials
- GET /api/materials?device_id=&type=&name=&page=&per_page=
- GET /api/materials/export?device_id=&type=&name=
说明：管理后台页面会通过会话访问这些接口，因此需要支持无 JWT 的会话回退。
"""
from __future__ import annotations
from typing import Any
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import DeviceMaterial, Device, MaterialCatalog, User, OperationLog
from ..extensions import db
from ..utils.security import merchant_scope_filter

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
