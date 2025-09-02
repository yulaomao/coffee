"""故障与工单 API：
- GET /api/faults
- POST /api/workorders
- PATCH /api/workorders/<id>
"""
from __future__ import annotations
from typing import Any
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import Fault, WorkOrder, Device
from ..extensions import db
from ..utils.security import merchant_scope_filter

bp = Blueprint("faults", __name__)


@bp.route("/api/faults")
@jwt_required()
def list_faults():
    claims = get_jwt_identity()
    q = Fault.query.join(Device, Fault.device_id == Device.id)
    # merchant_scope_filter 作用于含 merchant_id 的模型，此处用 Device.merchant_id 实现
    if claims.get("role") != "superadmin":
        q = q.filter(Device.merchant_id == claims.get("merchant_id"))
    q = q.with_entities(Fault)
    items = q.order_by(Fault.created_at.desc()).limit(200).all()
    fmt = request.args.get('format')
    if fmt == 'csv':
        from ..utils.helpers import csv_response
        rows = [[f.id, f.device_id, f.level, f.code, f.message, f.created_at.isoformat()] for f in items]
        return csv_response(["id","device_id","level","code","message","created_at"], rows, filename="faults.csv")
    return jsonify({"items": [
        {"id": f.id, "device_id": f.device_id, "level": f.level, "code": f.code, "message": f.message, "created_at": f.created_at.isoformat()}
        for f in items
    ]})


@bp.route("/api/workorders", methods=["POST"])
@jwt_required()
def create_workorder():
    claims = get_jwt_identity()
    data: dict[str, Any] = request.get_json(force=True)
    device_id = int(data.get("device_id"))
    # 多租户简单校验
    if claims.get("role") != "superadmin":
        dev = Device.query.get_or_404(device_id)
        if dev.merchant_id != claims.get("merchant_id"):
            return jsonify({"msg": "无权限"}), 403
    wo = WorkOrder(device_id=device_id, fault_id=data.get("fault_id"), status="pending", note=data.get("note"))
    db.session.add(wo)
    db.session.commit()
    return jsonify({"id": wo.id})


@bp.route("/api/workorders/<int:workorder_id>", methods=["PATCH"])
@jwt_required()
def update_workorder(workorder_id: int):
    data: dict[str, Any] = request.get_json(force=True)
    wo = WorkOrder.query.get_or_404(workorder_id)
    if "status" in data:
        wo.status = data["status"]
    if "assigned_to_user_id" in data:
        wo.assigned_to_user_id = data["assigned_to_user_id"]
    db.session.commit()
    return jsonify({"msg": "updated"})
