"""审计日志 API（最小实现）。
- GET /api/operation_logs
"""
from __future__ import annotations
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from ..models import OperationLog

bp = Blueprint("operation_logs", __name__)


@bp.route("/api/operation_logs")
@jwt_required()
def list_logs():
    items = OperationLog.query.order_by(OperationLog.created_at.desc()).limit(200).all()
    return jsonify({"items": [
        {"id": l.id, "action": l.action, "target_type": l.target_type, "created_at": l.created_at.isoformat()} for l in items
    ]})
