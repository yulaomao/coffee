"""订单管理 API（完整版）：
- GET /api/orders 列表（分页，筛选，CSV 导出）
- GET /api/orders/<order_no> 详情
- GET /api/orders/export 导出 CSV（记录操作日志）
- GET /api/orders/statistics 时间序列聚合
- GET /api/orders/rank 排名
- GET /api/orders/combo_analysis 组合分析
- GET /api/orders/exceptions 异常订单列表
- POST /api/orders/<order_no>/manual_refund 人工退款
- POST /api/orders/auto_refund_callback 渠道退款回调
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from flask import Blueprint, jsonify, request, session
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import func

from ..extensions import db
from ..models import OperationLog, Order, User
from ..utils.helpers import csv_response
from ..utils.security import merchant_scope_filter

bp = Blueprint("orders", __name__)


def _current_claims():
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


def _apply_filters(q, args):
    # 通用筛选：merchant/device/product/pay_method/date/exception
    merchant_id = args.get("merchant_id")
    device_id = args.get("device_id")
    product_id = args.get("product_id")
    pay_method = args.get("pay_method")
    pay_status = args.get("pay_status")
    is_exception = args.get("is_exception")
    from_s = args.get("from")
    to_s = args.get("to")
    if merchant_id:
        q = q.filter(Order.merchant_id == int(merchant_id))
    if device_id:
        q = q.filter(Order.device_id == int(device_id))
    if product_id:
        q = q.filter(Order.product_id == int(product_id))
    if pay_method:
        q = q.filter(Order.pay_method == pay_method)
    if pay_status:
        q = q.filter(Order.pay_status == pay_status)
    if is_exception is not None and is_exception != "":
        q = q.filter(Order.is_exception == (is_exception in ("1", "true", "True")))
    if from_s:
        try:
            q = q.filter(Order.created_at >= datetime.fromisoformat(from_s))
        except Exception:
            pass
    if to_s:
        try:
            q = q.filter(Order.created_at < datetime.fromisoformat(to_s) + timedelta(days=1))
        except Exception:
            pass
    return q


@bp.route("/api/orders")
@jwt_required(optional=True)
def list_orders():
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    q = merchant_scope_filter(Order.query, claims)
    q = _apply_filters(q, request.args)
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 200)
    total = q.count()
    items = q.order_by(Order.created_at.desc()).limit(per_page).offset((page - 1) * per_page).all()
    fmt = request.args.get("format")
    if fmt == "csv":
        rows = [
            [
                o.order_no or "",
                o.created_at.isoformat(),
                o.merchant_id,
                o.device_id,
                o.product_id or "",
                o.product_name or "",
                int(o.qty or 1),
                str(o.unit_price or 0),
                str(o.total_amount or 0),
                o.pay_method,
                o.pay_status,
                int(o.is_exception),
            ]
            for o in items
        ]
        # 记录导出日志
        try:
            db.session.add(
                OperationLog(
                    user_id=claims.get("id"),
                    action="export",
                    target_type="orders",
                    target_id=None,
                    ip=None,
                    user_agent=None,
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
        return csv_response(
            [
                "order_no",
                "created_at",
                "merchant_id",
                "device_id",
                "product_id",
                "product_name",
                "qty",
                "unit_price",
                "total_amount",
                "pay_method",
                "pay_status",
                "is_exception",
            ],
            rows,
            filename="orders.csv",
        )
    return jsonify(
        {
            "total": total,
            "page": page,
            "per_page": per_page,
            "items": [
                {
                    "order_no": o.order_no,
                    "created_at": o.created_at.isoformat(),
                    "merchant_id": o.merchant_id,
                    "device_id": o.device_id,
                    "product_id": o.product_id,
                    "product_name": o.product_name,
                    "qty": int(o.qty or 1),
                    "unit_price": float(o.unit_price or 0),
                    "total_amount": float(o.total_amount or 0),
                    "pay_method": o.pay_method,
                    "pay_status": o.pay_status or o.status,
                    "is_exception": bool(o.is_exception),
                }
                for o in items
            ],
        }
    )


@bp.route("/api/orders/<string:order_no>")
@jwt_required(optional=True)
def order_detail(order_no: str):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    q = merchant_scope_filter(Order.query, claims)
    o = q.filter_by(order_no=order_no).first_or_404()
    return jsonify(
        {
            "order_no": o.order_no,
            "created_at": o.created_at.isoformat(),
            "merchant_id": o.merchant_id,
            "device_id": o.device_id,
            "product_id": o.product_id,
            "product_name": o.product_name,
            "qty": int(o.qty or 1),
            "unit_price": float(o.unit_price or 0),
            "total_amount": float(o.total_amount or 0),
            "pay_method": o.pay_method,
            "pay_status": o.pay_status or o.status,
            "is_exception": bool(o.is_exception),
            "raw_payload": o.raw_payload,
            "refund_info": o.refund_info,
            "created_by": o.created_by,
        }
    )


@bp.route("/api/orders/export")
@jwt_required(optional=True)
def export_orders():
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    q = merchant_scope_filter(Order.query, claims)
    q = _apply_filters(q, request.args)
    items = q.order_by(Order.created_at.desc()).all()
    rows = [
        [
            o.order_no or "",
            o.created_at.isoformat(),
            o.merchant_id,
            o.device_id,
            o.product_id or "",
            o.product_name or "",
            int(o.qty or 1),
            str(o.unit_price or 0),
            str(o.total_amount or 0),
            o.pay_method,
            o.pay_status,
            int(o.is_exception),
        ]
        for o in items
    ]
    try:
        db.session.add(
            OperationLog(
                user_id=claims.get("id"),
                action="export",
                target_type="orders",
                target_id=None,
                ip=None,
                user_agent=None,
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
    return csv_response(
        [
            "order_no",
            "created_at",
            "merchant_id",
            "device_id",
            "product_id",
            "product_name",
            "qty",
            "unit_price",
            "total_amount",
            "pay_method",
            "pay_status",
            "is_exception",
        ],
        rows,
        filename="orders_export.csv",
    )


@bp.route("/api/orders/statistics")
@jwt_required(optional=True)
def orders_statistics():
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    group_by = request.args.get("group_by", "day")
    metric = request.args.get("metric", "amount")  # amount|count
    q = merchant_scope_filter(Order.query, claims)
    q = _apply_filters(q, request.args)
    # 时间分组表达式
    if group_by == "year":
        key = func.strftime("%Y", Order.created_at)
    elif group_by == "month":
        key = func.strftime("%Y-%m", Order.created_at)
    else:
        key = func.strftime("%Y-%m-%d", Order.created_at)
    agg = func.sum(Order.total_amount) if metric == "amount" else func.count(Order.id)
    rows = (
        db.session.query(key.label("k"), agg.label("v"))
        .select_from(Order)
        .filter(q.whereclause)
        .group_by("k")
        .order_by("k")
        .all()
    )
    return jsonify([{"k": r[0], "v": float(r[1]) if r[1] is not None else 0} for r in rows])


@bp.route("/api/orders/rank")
@jwt_required(optional=True)
def orders_rank():
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    by = request.args.get("by", "product")  # product|device
    metric = request.args.get("metric", "amount")
    limit = int(request.args.get("limit", 20))
    q = merchant_scope_filter(Order.query, claims)
    q = _apply_filters(q, request.args)
    if by == "device":
        key = Order.device_id
    else:
        key = Order.product_id
    agg = func.sum(Order.total_amount) if metric == "amount" else func.count(Order.id)
    rows = (
        db.session.query(key.label("k"), agg.label("v"))
        .select_from(Order)
        .filter(q.whereclause)
        .group_by("k")
        .order_by(
            func.coalesce(
                func.sum(Order.total_amount) if metric == "amount" else func.count(Order.id), 0
            ).desc()
        )
        .limit(limit)
        .all()
    )
    return jsonify([{"k": r[0], "v": float(r[1]) if r[1] is not None else 0} for r in rows])


@bp.route("/api/orders/combo_analysis")
@jwt_required(optional=True)
def orders_combo():
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    group_by = request.args.get("group_by", "product,pay_method")
    q = merchant_scope_filter(Order.query, claims)
    q = _apply_filters(q, request.args)
    keys = [k.strip() for k in group_by.split(",") if k.strip()]
    cols = []
    for k in keys:
        if k == "product":
            cols.append(Order.product_id)
        elif k == "pay_method":
            cols.append(Order.pay_method)
        elif k == "device":
            cols.append(Order.device_id)
        else:
            cols.append(Order.pay_method)
    rows = (
        db.session.query(*cols, func.sum(Order.total_amount), func.count(Order.id))
        .select_from(Order)
        .filter(q.whereclause)
        .group_by(*cols)
        .all()
    )
    result = []
    for r in rows:
        d = {f"g{i}": r[i] for i in range(len(cols))}
        d["amount"] = float(r[len(cols)])
        d["count"] = int(r[len(cols) + 1])
        result.append(d)
    return jsonify(result)


@bp.route("/api/orders/exceptions")
@jwt_required(optional=True)
def orders_exceptions():
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    q = merchant_scope_filter(Order.query, claims)
    q = _apply_filters(q, request.args)
    q = q.filter(Order.is_exception == True)
    items = q.order_by(Order.created_at.desc()).limit(500).all()
    return jsonify(
        [
            {
                "order_no": o.order_no,
                "created_at": o.created_at.isoformat(),
                "device_id": o.device_id,
                "pay_method": o.pay_method,
                "pay_status": o.pay_status,
                "refund_info": o.refund_info,
            }
            for o in items
        ]
    )


@bp.route("/api/orders/<string:order_no>/manual_refund", methods=["POST"])
@jwt_required(optional=True)
def manual_refund(order_no: str):
    claims = _current_claims()
    if not claims:
        return jsonify({"msg": "unauthorized"}), 401
    o = merchant_scope_filter(Order.query, claims).filter_by(order_no=order_no).first_or_404()
    data = request.get_json(force=True) or {}
    reason = data.get("reason", "manual")
    # 退款逻辑 stub：记录 refund_info，并置 pay_status
    o.pay_status = "refund_pending"
    o.refund_info = {
        "by": claims.get("id"),
        "reason": reason,
        "requested_at": datetime.utcnow().isoformat(),
    }
    db.session.add(
        OperationLog(
            user_id=claims.get("id"),
            action="manual_refund",
            target_type="order",
            target_id=o.id,
            ip=None,
            user_agent=None,
        )
    )
    db.session.commit()
    return jsonify({"msg": "refund_requested"})


@bp.route("/api/orders/auto_refund_callback", methods=["POST"])
def auto_refund_callback():
    data = request.get_json(force=True) or {}
    order_no = data.get("order_no")
    status = data.get("status")  # success/failed
    o = Order.query.filter_by(order_no=order_no).first()
    if not o:
        return jsonify({"msg": "order not found"}), 404
    if status == "success":
        o.pay_status = "refunded"
    else:
        o.pay_status = "failed"
    info = o.refund_info or {}
    info.update({"callback": data, "updated_at": datetime.utcnow().isoformat()})
    o.refund_info = info
    db.session.commit()
    return jsonify({"msg": "ok"})
