"""物料管理 API（最小实现）：
- GET/PUT /api/devices/<id>/materials
"""
from __future__ import annotations
from typing import Any
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import DeviceMaterial
from ..extensions import db
from ..utils.security import merchant_scope_filter

bp = Blueprint("materials", __name__)


@bp.route("/api/devices/<int:device_id>/materials", methods=["GET", "PUT"])
@jwt_required()
def device_materials(device_id: int):
    claims = get_jwt_identity()
    q = DeviceMaterial.query.filter_by(device_id=device_id)
    q = merchant_scope_filter(q, claims)
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
