"""订单管理 API：
- GET /api/orders 支持筛选与 CSV 导出
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..extensions import db
from ..models import Order
from ..utils.helpers import csv_response
from ..utils.security import merchant_scope_filter

bp = Blueprint("orders", __name__)


@bp.route("/api/orders")
@jwt_required()
def list_orders():
    claims = get_jwt_identity()
    q = Order.query
    q = merchant_scope_filter(q, claims)
    device_id = request.args.get("device_id")
    if device_id:
        q = q.filter_by(device_id=int(device_id))
    pay_method = request.args.get("pay_method")
    if pay_method:
        q = q.filter_by(pay_method=pay_method)
    fmt = request.args.get("format")
    orders = q.order_by(Order.created_at.desc()).limit(500).all()
    if fmt == "csv":
        rows = [[o.id, o.order_no or '', o.device_id, o.price, o.pay_method, o.status, o.created_at.isoformat()] for o in orders]
        return csv_response(["id","order_no","device_id","price","pay_method","status","created_at"], rows, filename="orders.csv")
    return jsonify({"items": [
        {"id": o.id, "order_no": o.order_no, "device_id": o.device_id, "price": o.price, "pay_method": o.pay_method, "status": o.status, "created_at": o.created_at.isoformat()} for o in orders
    ]})
