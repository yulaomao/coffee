"""仪表盘与页面路由（最小实现）。"""
from __future__ import annotations
from datetime import datetime, timedelta, date
from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..extensions import db
from ..models import Device, Order, Fault, DeviceMaterial, Merchant, MaterialCatalog

bp = Blueprint("admin", __name__, url_prefix="")


@bp.before_app_request
def ensure_login():
    # 简单页面会话保护，不影响 API 的 JWT 保护
    from flask import request as flask_request
    if flask_request.path.startswith("/api/"):
        return
    if flask_request.endpoint in {"auth.login_page", "static"}:
        return
    if session.get("user_id") is None:
        # 放过登录页，其他页面跳转
        if not flask_request.path.startswith("/login"):
            return redirect(url_for("auth.login_page"))


@bp.route("/dashboard")
def dashboard():
    # 基础数字用于首屏占位，实际图表/卡片将通过 API 动态刷新
    device_count = Device.query.count()
    fault_count = Fault.query.count()
    order_today = Order.query.filter(Order.created_at >= datetime.utcnow().date(), Order.pay_status == "paid").count()
    revenue_today = db.session.query(db.func.sum(Order.total_amount)).filter(Order.created_at >= datetime.utcnow().date(), Order.pay_status == "paid").scalar() or 0
    merchants = Merchant.query.order_by(Merchant.id.asc()).all()
    return render_template("dashboard.html", device_count=device_count, fault_count=fault_count, order_today=order_today, revenue_today=revenue_today, merchants=merchants)


def _daterange(from_str: str | None, to_str: str | None):
    # 解析日期范围，默认最近 30 天（含今天）
    try:
        to_d = datetime.strptime(to_str, "%Y-%m-%d").date() if to_str else date.today()
    except Exception:
        to_d = date.today()
    try:
        from_d = datetime.strptime(from_str, "%Y-%m-%d").date() if from_str else to_d - timedelta(days=29)
    except Exception:
        from_d = to_d - timedelta(days=29)
    if from_d > to_d:
        from_d, to_d = to_d, from_d
    days = []
    d = from_d
    while d <= to_d:
        days.append(d)
        d += timedelta(days=1)
    return from_d, to_d, days


def _aggregate_summary(query_params: dict, claims: dict | None = None):
    from_str = query_params.get("from")
    to_str = query_params.get("to")
    merchant_id = query_params.get("merchant_id")
    from_d, to_d, days = _daterange(from_str, to_str)

    # 作用域过滤
    q_device = Device.query
    q_order = Order.query
    q_fault = Fault.query.join(Device, Fault.device_id == Device.id)
    if merchant_id:
        try:
            mid = int(merchant_id)
            q_device = q_device.filter(Device.merchant_id == mid)
            q_order = q_order.filter(Order.merchant_id == mid)
            q_fault = q_fault.join(Device, Fault.device_id == Device.id).filter(Device.merchant_id == mid)
        except Exception:
            pass
    if claims:
        from ..utils.security import merchant_scope_filter
        q_device = merchant_scope_filter(q_device, claims)
        q_order = merchant_scope_filter(q_order, claims)
        # 对 Fault 使用基于角色的商户过滤（join 了 Device）
        try:
            role = claims.get('role')
            mid = claims.get('merchant_id')
            if role != 'superadmin' and mid:
                q_fault = q_fault.filter(Device.merchant_id == int(mid))
        except Exception:
            pass

    device_total = q_device.count()

    # 按天聚合订单
    series_dates = [d.strftime("%Y-%m-%d") for d in days]
    sales_series: list[int] = []
    revenue_series: list[float] = []
    active_devices_series: list[int] = []
    online_rate_series: list[float] = []
    for d in days:
        start_dt = datetime.combine(d, datetime.min.time())
        end_dt = start_dt + timedelta(days=1)
        qd = q_order.filter(Order.created_at >= start_dt, Order.created_at < end_dt, Order.pay_status == "paid")
        sales = qd.count()
        revenue = qd.with_entities(db.func.coalesce(db.func.sum(Order.total_amount), 0.0)).scalar() or 0.0
        # 活跃设备：当天产生过订单的设备数（在 q_order 作用域内）
        active = qd.with_entities(db.func.count(db.func.distinct(Order.device_id))).scalar() or 0
        # 在线率：用活跃设备/总设备 近似（示例数据）
        online_rate = round((active / device_total) * 100, 2) if device_total else 0.0
        sales_series.append(sales)
        revenue_series.append(float(revenue))
        active_devices_series.append(int(active))
        online_rate_series.append(online_rate)

    # 故障分布（按 level）
    fault_counts = []
    if days:
        start_all = datetime.combine(days[0], datetime.min.time())
        end_all = datetime.combine(days[-1] + timedelta(days=1), datetime.min.time())
        fq = q_fault.filter(Fault.created_at >= start_all, Fault.created_at < end_all)
        fault_counts = (
            fq.with_entities(Fault.level, db.func.count(Fault.id))
            .group_by(Fault.level)
            .all()
        )
    fault_labels = [r[0] for r in fault_counts]
    fault_data = [int(r[1]) for r in fault_counts]

    # 物料风险与告警
    # 告警 Top5（remain<threshold）与 即将告警 Top5（threshold<=remain<=1.2*threshold）
    alerts_q = (
        db.session.query(DeviceMaterial, Device, MaterialCatalog)
        .join(Device, Device.id == DeviceMaterial.device_id)
        .outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceMaterial.material_id)
        .filter(DeviceMaterial.remain < DeviceMaterial.threshold)
    )
    if merchant_id:
        try:
            alerts_q = alerts_q.filter(Device.merchant_id == int(merchant_id))
        except Exception:
            pass
    if claims:
        try:
            role = claims.get('role')
            mid = claims.get('merchant_id')
            if role != 'superadmin' and mid:
                alerts_q = alerts_q.filter(Device.merchant_id == int(mid))
        except Exception:
            pass
    alerts = alerts_q.order_by((DeviceMaterial.remain / db.func.nullif(DeviceMaterial.threshold, 0)).asc()).limit(5).all()
    alert_list = []
    for dm, dev, mc in alerts:
        alert_list.append({
            "device_no": dev.device_no,
            "device_id": dev.id,
            "material_id": dm.material_id,
            "material_name": mc.name if mc else f"材料{dm.material_id}",
            "unit": (mc.unit if mc else ""),
            "remain": float(dm.remain),
            "capacity": float(getattr(dm, 'capacity', 0.0)),
            "threshold": float(dm.threshold),
            "percent": round((dm.remain / dm.threshold) * 100, 1) if dm.threshold else 0,
            "stock_percent": round((dm.remain / dm.capacity) * 100, 1) if getattr(dm, 'capacity', 0) else None,
            "severity": "critical" if dm.remain <= 0 else "warning",
        })

    # 即将告警 Top5（阈值>0 且 remain 介于 [threshold, 1.2*threshold]）
    near_factor = 1.2
    near_q = (
        db.session.query(DeviceMaterial, Device, MaterialCatalog)
        .join(Device, Device.id == DeviceMaterial.device_id)
        .outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceMaterial.material_id)
        .filter(DeviceMaterial.threshold > 0)
        .filter(DeviceMaterial.remain >= DeviceMaterial.threshold)
        .filter(DeviceMaterial.remain <= DeviceMaterial.threshold * near_factor)
    )
    if merchant_id:
        try:
            near_q = near_q.filter(Device.merchant_id == int(merchant_id))
        except Exception:
            pass
    if claims:
        try:
            role = claims.get('role')
            mid = claims.get('merchant_id')
            if role != 'superadmin' and mid:
                near_q = near_q.filter(Device.merchant_id == int(mid))
        except Exception:
            pass
    near_rows = near_q.order_by((DeviceMaterial.remain / db.func.nullif(DeviceMaterial.threshold, 1)).asc()).limit(5).all()
    near_list = []
    for dm, dev, mc in near_rows:
        near_list.append({
            "device_no": dev.device_no,
            "device_id": dev.id,
            "material_id": dm.material_id,
            "material_name": mc.name if mc else f"材料{dm.material_id}",
            "unit": (mc.unit if mc else ""),
            "remain": float(dm.remain),
            "capacity": float(getattr(dm, 'capacity', 0.0)),
            "threshold": float(dm.threshold),
            "percent": round((dm.remain / dm.threshold) * 100, 1) if dm.threshold else 0,
            "stock_percent": round((dm.remain / dm.capacity) * 100, 1) if getattr(dm, 'capacity', 0) else None,
            "severity": "near",
        })

    # 告警统计计数
    base_m_q = db.session.query(DeviceMaterial).join(Device, Device.id == DeviceMaterial.device_id)
    if merchant_id:
        try:
            base_m_q = base_m_q.filter(Device.merchant_id == int(merchant_id))
        except Exception:
            pass
    if claims:
        try:
            role = claims.get('role')
            mid = claims.get('merchant_id')
            if role != 'superadmin' and mid:
                base_m_q = base_m_q.filter(Device.merchant_id == int(mid))
        except Exception:
            pass
    critical_count = base_m_q.filter(DeviceMaterial.remain <= 0).count()
    warning_count = base_m_q.filter(DeviceMaterial.remain > 0, DeviceMaterial.remain < DeviceMaterial.threshold).count()
    near_count = base_m_q.filter(DeviceMaterial.threshold > 0, DeviceMaterial.remain >= DeviceMaterial.threshold, DeviceMaterial.remain <= DeviceMaterial.threshold * near_factor).count()

    # KPI 计算（以最后一天为“今日”）
    sales_today = sales_series[-1] if sales_series else 0
    revenue_today = revenue_series[-1] if revenue_series else 0.0
    online_rate_today = online_rate_series[-1] if online_rate_series else 0.0
    def change_rate(cur: float, prev: float):
        if prev == 0:
            return None
        return round((cur - prev) / prev * 100, 2)
    yoy = change_rate(sales_today, sales_series[-2] if len(sales_series) > 1 else 0)
    mom = change_rate(revenue_today, revenue_series[-2] if len(revenue_series) > 1 else 0)

    result = {
        # 兼容旧字段
        "device_total": device_total,
        "order_today": sales_today,
        "revenue_today": float(revenue_today),
        "fault_count": sum(fault_data) if fault_data else 0,
        # 新字段
        "kpis": {
            "device_total": device_total,
            "online_rate": online_rate_today,
            "sales_today": sales_today,
            "revenue_today": float(revenue_today),
            "changes": {"sales_yoy": yoy, "revenue_mom": mom}
        },
        "series": {
            "dates": series_dates,
            "online_rate": online_rate_series,
            "active_devices": active_devices_series,
            "daily_sales": sales_series,
            "daily_revenue": revenue_series,
        },
        "faults_pie": {"labels": fault_labels, "data": fault_data},
    "materials_alert_top5": alert_list,
    "materials_near_top5": near_list,
    "materials_alert_stats": {"critical": int(critical_count), "warning": int(warning_count), "near": int(near_count)},
    }
    return result


@bp.route("/api/demo/load", methods=["POST"])
def api_demo_load():
    # 轻量入口：调用脚本逻辑（直接复用 seed_demo.gen_demo）
    from scripts.seed_demo import gen_demo  # type: ignore
    params = request.get_json(silent=True) or {}
    gen_demo(
        devices=int(params.get("devices", 200)),
        orders=int(params.get("orders", 5000)),
        online_rate=float(params.get("online_rate", 0.7)),
        fault_rate=float(params.get("fault_rate", 0.05)),
    )
    session["demo_mode"] = True
    return jsonify({"msg": "demo loaded"})


@bp.route("/api/demo/clear", methods=["POST"])
def api_demo_clear():
    from ..models import Order, Fault, WorkOrder, Device
    from ..extensions import db
    # 清空演示数据（保留管理员与默认商户）
    Order.query.delete()
    WorkOrder.query.delete()
    Fault.query.delete()
    Device.query.filter(Device.device_no.like("DEMO-%")).delete()
    db.session.commit()
    session["demo_mode"] = False
    return jsonify({"msg": "demo cleared"})


@bp.route("/api/dashboard/summary")
@jwt_required()
def api_dashboard_summary():
    claims = get_jwt_identity()
    return _aggregate_summary(request.args, claims)


@bp.route("/api/dashboard/summary_public")
def api_dashboard_summary_public():
    # 供管理页面使用的公开接口（基于会话），返回结构与 /api/dashboard/summary 相同
    return _aggregate_summary(request.args, None)


@bp.route("/devices")
def devices_page():
    devices = Device.query.order_by(Device.created_at.desc()).limit(50).all()
    merchants = Merchant.query.order_by(Merchant.id.asc()).all()
    return render_template("devices.html", devices=devices, merchants=merchants)


@bp.route("/devices/<int:device_id>")
def device_detail_page(device_id: int):
    device = Device.query.get_or_404(device_id)
    recent_orders = Order.query.filter_by(device_id=device.id).order_by(Order.created_at.desc()).limit(10).all()
    return render_template("device_detail.html", device=device, recent_orders=recent_orders)

# 通过设备编号访问详情，便于前端链接（重用上面的模板）
@bp.route("/devices/<string:device_no>")
def device_detail_by_no(device_no: str):
    device = Device.query.filter_by(device_no=device_no).first_or_404()
    recent_orders = Order.query.filter_by(device_id=device.id).order_by(Order.created_at.desc()).limit(10).all()
    return render_template("device_detail.html", device=device, recent_orders=recent_orders)


@bp.route("/orders")
def orders_page():
    return render_template("orders_list.html")

@bp.route("/orders/exceptions")
def orders_exceptions_page():
    return render_template("orders_exceptions.html")

@bp.route("/orders/charts")
def orders_charts_page():
    return render_template("orders_charts.html")


@bp.route("/upgrades")
def upgrades_page():
    return render_template("upgrades.html")


@bp.route("/recipes")
def recipes_page():
    return render_template("recipes.html")


@bp.route("/materials_manage")
def materials_manage_page():
    return render_template("material_manage_new.html")

@bp.route("/materials_manage_old")
def materials_manage_old_page():
    """旧版物料管理页面，保留作为备份"""
    return render_template("material_manage.html")


# 新物料字典与料盒页面
@bp.route("/materials")
def materials_catalog_page():
    devices = Device.query.order_by(Device.created_at.desc()).limit(200).all()
    return render_template("materials.html", devices=devices)


@bp.route("/devices/<int:device_id>/bins_page")
def device_bins_page(device_id: int):
    d = Device.query.get_or_404(device_id)
    return render_template("device_bins.html", device=d)


@bp.route("/devices/bins/bulk")
def device_bins_bulk_page():
    return render_template("device_bins_bulk.html")


@bp.route("/faults")
def faults_page():
    faults = Fault.query.order_by(Fault.created_at.desc()).limit(100).all()
    return render_template("faults.html", faults=faults)


@bp.route("/workorders")
def workorders_page():
    return render_template("workorders.html")


@bp.route("/finance")
def finance_page():
    return render_template("finance.html")


@bp.route("/logs")
def logs_page():
    return render_template("logs.html")


@bp.route("/tasks")
def tasks_page():
    return render_template("tasks.html")
