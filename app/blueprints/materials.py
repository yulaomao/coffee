"""物料管理 API：
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

import csv
from datetime import datetime
from io import StringIO
from typing import Any, Optional

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from ..extensions import db
from ..models import Device, DeviceBin, MaterialCatalog, OperationLog, RemoteCommand, User
from ..utils.security import merchant_scope_filter

bp = Blueprint("materials", __name__)


def _current_claims():
    """获取当前用户声明，优先 JWT，回退到会话，返回 {id, role, merchant_id} 或 None"""
    try:
        claims = get_jwt_identity()
        if claims:
            return claims
    except Exception:
        pass

    # 会话回退
    from flask import session

    user_id = session.get("user_id")
    if user_id:
        try:
            user = User.query.get(int(user_id))
            if user:
                return {"id": user.id, "role": user.role, "merchant_id": user.merchant_id}
        except Exception:
            pass

    return None


def _require_write(claims) -> Optional[tuple[str, int]]:
    """检查写操作权限"""
    if not claims:
        return ("未授权：需要登录", 401)

    role = claims.get("role")
    if role not in {"superadmin", "merchant_admin", "ops_engineer"}:
        return ("权限不足：需要管理员权限", 403)

    return None


def _validate_material_data(data: dict) -> Optional[str]:
    """验证物料数据的完整性和合法性"""
    if not data.get("name", "").strip():
        return "物料名称不能为空"

    unit = data.get("unit", "").strip()
    if unit and unit not in ["g", "ml", "pcs", "个", "包", "kg", "l"]:
        return "单位必须是: g, ml, pcs, 个, 包, kg, l 之一"

    try:
        if data.get("default_capacity") is not None:
            capacity = float(data["default_capacity"])
            if capacity <= 0:
                return "默认容量必须大于0"
    except (ValueError, TypeError):
        return "默认容量必须是有效数字"

    return None


# ==================== 物料管理统计 ====================


@bp.route("/api/materials/overview")
@jwt_required(optional=True)
def materials_overview():
    """获取物料管理概览统计数据"""
    claims = _current_claims()
    if not claims:
        return jsonify({"ok": False, "message": "需要登录"}), 401

    try:
        # 统计设备数量
        total_devices = Device.query.count()
        online_devices = Device.query.filter_by(status="online").count()

        # 统计物料种类
        total_materials = MaterialCatalog.query.filter_by(is_active=True).count()

        # 统计料盒总数
        total_bins = DeviceBin.query.count()
        online_bins = (
            db.session.query(DeviceBin).join(Device).filter(Device.status == "online").count()
        )

        # 统计低库存料盒 (remaining < capacity * 0.2)
        low_stock_bins = (
            db.session.query(DeviceBin)
            .filter(DeviceBin.remaining < DeviceBin.capacity * 0.2, DeviceBin.capacity > 0)
            .count()
        )

        # 统计物料使用情况
        material_usage = (
            db.session.query(
                MaterialCatalog.code,
                MaterialCatalog.name,
                db.func.count(DeviceBin.id).label("bin_count"),
            )
            .outerjoin(DeviceBin, MaterialCatalog.id == DeviceBin.material_id)
            .filter(MaterialCatalog.is_active == True)
            .group_by(MaterialCatalog.id, MaterialCatalog.code, MaterialCatalog.name)
            .order_by(db.func.count(DeviceBin.id).desc())
            .all()
        )

        return jsonify(
            {
                "ok": True,
                "data": {
                    "total_devices": total_devices,
                    "online_devices": online_devices,
                    "total_materials": total_materials,
                    "total_bins": total_bins,
                    "online_bins": online_bins,
                    "low_stock_bins": low_stock_bins,
                    "material_usage": [
                        {"code": code, "name": name, "bin_count": bin_count}
                        for code, name, bin_count in material_usage
                    ],
                },
            }
        )

    except Exception as e:
        return jsonify({"ok": False, "message": f"获取统计数据失败: {str(e)}"}), 500


# ==================== 物料字典管理 ====================


@bp.route("/api/material_catalog")
@jwt_required(optional=True)
def list_material_catalog():
    """获取物料字典列表，支持分页和筛选"""
    claims = _current_claims()
    if not claims:
        return jsonify({"ok": False, "message": "需要登录"}), 401

    try:
        q = MaterialCatalog.query.filter_by(is_active=True)

        # 筛选参数
        keyword = request.args.get("q", "").strip()
        category = request.args.get("category", "").strip()

        if keyword:
            q = q.filter(
                (MaterialCatalog.name.like(f"%{keyword}%"))
                | (MaterialCatalog.code.like(f"%{keyword}%"))
            )

        if category:
            q = q.filter(MaterialCatalog.category == category)

        # 分页
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(200, max(1, int(request.args.get("per_page", 50))))
        total = q.count()

        items = (
            q.order_by(MaterialCatalog.id.asc()).limit(per_page).offset((page - 1) * per_page).all()
        )

        # CSV导出
        if request.args.get("format") == "csv":
            from ..utils.helpers import csv_response

            rows = [
                [
                    m.id,
                    m.code or "",
                    m.name,
                    m.category or "",
                    m.unit,
                    m.default_capacity or 0,
                    m.description or "",
                    m.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                ]
                for m in items
            ]
            return csv_response(
                [
                    "id",
                    "code",
                    "name",
                    "category",
                    "unit",
                    "default_capacity",
                    "description",
                    "created_at",
                ],
                rows,
                filename="material_catalog.csv",
            )

        return jsonify(
            {
                "ok": True,
                "total": total,
                "page": page,
                "per_page": per_page,
                "items": [
                    {
                        "id": m.id,
                        "code": m.code,
                        "name": m.name,
                        "category": m.category,
                        "unit": m.unit,
                        "default_capacity": m.default_capacity,
                        "description": m.description,
                        "created_at": m.created_at.isoformat(),
                        "is_active": m.is_active,
                    }
                    for m in items
                ],
            }
        )

    except Exception as e:
        return jsonify({"ok": False, "message": f"查询失败: {str(e)}"}), 500


@bp.route("/api/material_catalog", methods=["POST"])
@jwt_required(optional=True)
def create_material_catalog():
    """创建新的物料字典项"""
    claims = _current_claims()
    error = _require_write(claims)
    if error:
        return jsonify({"ok": False, "message": error[0]}), error[1]

    try:
        data = request.get_json(force=True) or {}

        # 验证数据
        validation_error = _validate_material_data(data)
        if validation_error:
            return jsonify({"ok": False, "message": validation_error}), 400

        # 检查代码唯一性（如果提供）
        code = data.get("code", "").strip()
        if code and MaterialCatalog.query.filter_by(code=code, is_active=True).first():
            return jsonify({"ok": False, "message": f"物料代码 '{code}' 已存在"}), 400

        # 检查名称唯一性
        name = data["name"].strip()
        if MaterialCatalog.query.filter_by(name=name, is_active=True).first():
            return jsonify({"ok": False, "message": f"物料名称 '{name}' 已存在"}), 400

        material = MaterialCatalog(
            code=code if code else None,
            name=name,
            category=data.get("category", "").strip() or None,
            unit=data.get("unit", "g"),
            default_capacity=float(data.get("default_capacity", 100)),
            description=data.get("description", "").strip() or None,
            created_by=claims.get("id"),
            is_active=True,
        )

        db.session.add(material)
        db.session.commit()

        # 记录操作日志
        try:
            db.session.add(
                OperationLog(
                    user_id=claims.get("id"),
                    action="material_catalog_create",
                    target_type="material_catalog",
                    target_id=material.id,
                    ip=request.remote_addr,
                    user_agent=request.user_agent.string[:500] if request.user_agent else None,
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

        return jsonify({"ok": True, "material_id": material.id, "message": "物料创建成功"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": f"创建失败: {str(e)}"}), 500


@bp.route("/api/material_catalog/<int:material_id>")
@jwt_required(optional=True)
def get_material_catalog(material_id: int):
    """获取单个物料字典项详情"""
    claims = _current_claims()
    if not claims:
        return jsonify({"ok": False, "message": "需要登录"}), 401

    material = MaterialCatalog.query.filter_by(id=material_id, is_active=True).first()
    if not material:
        return jsonify({"ok": False, "message": "物料不存在"}), 404

    return jsonify(
        {
            "ok": True,
            "material": {
                "id": material.id,
                "code": material.code,
                "name": material.name,
                "category": material.category,
                "unit": material.unit,
                "default_capacity": material.default_capacity,
                "description": material.description,
                "created_at": material.created_at.isoformat(),
                "is_active": material.is_active,
            },
        }
    )


@bp.route("/api/material_catalog/<int:material_id>", methods=["PUT"])
@jwt_required(optional=True)
def update_material_catalog(material_id: int):
    """更新物料字典项"""
    claims = _current_claims()
    error = _require_write(claims)
    if error:
        return jsonify({"ok": False, "message": error[0]}), error[1]

    try:
        material = MaterialCatalog.query.filter_by(id=material_id, is_active=True).first()
        if not material:
            return jsonify({"ok": False, "message": "物料不存在"}), 404

        data = request.get_json(force=True) or {}

        # 验证数据
        validation_error = _validate_material_data(data)
        if validation_error:
            return jsonify({"ok": False, "message": validation_error}), 400

        # 检查代码唯一性（如果更改了代码）
        new_code = data.get("code", "").strip()
        if new_code and new_code != material.code:
            if MaterialCatalog.query.filter_by(code=new_code, is_active=True).first():
                return jsonify({"ok": False, "message": f"物料代码 '{new_code}' 已存在"}), 400

        # 检查名称唯一性（如果更改了名称）
        new_name = data["name"].strip()
        if new_name != material.name:
            if MaterialCatalog.query.filter_by(name=new_name, is_active=True).first():
                return jsonify({"ok": False, "message": f"物料名称 '{new_name}' 已存在"}), 400

        # 更新字段
        material.code = new_code if new_code else None
        material.name = new_name
        material.category = data.get("category", "").strip() or None
        material.unit = data.get("unit", material.unit)
        material.default_capacity = float(data.get("default_capacity", material.default_capacity))
        material.description = data.get("description", "").strip() or None

        db.session.commit()

        # 记录操作日志
        try:
            db.session.add(
                OperationLog(
                    user_id=claims.get("id"),
                    action="material_catalog_update",
                    target_type="material_catalog",
                    target_id=material.id,
                    ip=request.remote_addr,
                    user_agent=request.user_agent.string[:500] if request.user_agent else None,
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

        return jsonify({"ok": True, "message": "物料更新成功"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": f"更新失败: {str(e)}"}), 500


@bp.route("/api/material_catalog/<int:material_id>", methods=["DELETE"])
@jwt_required(optional=True)
def delete_material_catalog(material_id: int):
    """删除物料字典项（软删除）"""
    claims = _current_claims()
    error = _require_write(claims)
    if error:
        return jsonify({"ok": False, "message": error[0]}), error[1]

    try:
        material = MaterialCatalog.query.filter_by(id=material_id, is_active=True).first()
        if not material:
            return jsonify({"ok": False, "message": "物料不存在"}), 404

        # 检查是否有设备料盒在使用此物料
        bins_using = DeviceBin.query.filter_by(material_id=material_id).count()
        if bins_using > 0:
            return (
                jsonify(
                    {"ok": False, "message": f"无法删除：有 {bins_using} 个设备料盒正在使用此物料"}
                ),
                400,
            )

        # 软删除
        material.is_active = False
        db.session.commit()

        # 记录操作日志
        try:
            db.session.add(
                OperationLog(
                    user_id=claims.get("id"),
                    action="material_catalog_delete",
                    target_type="material_catalog",
                    target_id=material.id,
                    ip=request.remote_addr,
                    user_agent=request.user_agent.string[:500] if request.user_agent else None,
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

        return jsonify({"ok": True, "message": "物料删除成功"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": f"删除失败: {str(e)}"}), 500


# ==================== 设备料盒管理 ====================


@bp.route("/api/devices/<int:device_id>/bins")
@jwt_required(optional=True)
def get_device_bins(device_id: int):
    """获取设备的料盒配置"""
    claims = _current_claims()
    if not claims:
        return jsonify({"ok": False, "message": "需要登录"}), 401

    try:
        # 权限检查
        device = Device.query.get(device_id)
        if not device:
            return jsonify({"ok": False, "message": "设备不存在"}), 404

        role = claims.get("role")
        merchant_id = claims.get("merchant_id")
        if role != "superadmin" and merchant_id and device.merchant_id != int(merchant_id):
            return jsonify({"ok": False, "message": "无权限访问此设备"}), 403

        # 获取料盒信息
        bins = (
            db.session.query(DeviceBin, MaterialCatalog)
            .outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceBin.material_id)
            .filter(DeviceBin.device_id == device_id)
            .order_by(DeviceBin.bin_index.asc())
            .all()
        )

        bin_list = []
        for bin_obj, material in bins:
            bin_list.append(
                {
                    "bin_index": bin_obj.bin_index,
                    "material_id": bin_obj.material_id,
                    "material_name": material.name if material else None,
                    "material_code": material.code if material else None,
                    "capacity": bin_obj.capacity,
                    "remaining": bin_obj.remaining,
                    "unit": bin_obj.unit,
                    "custom_label": bin_obj.custom_label,
                    "last_sync_at": (
                        bin_obj.last_sync_at.isoformat() if bin_obj.last_sync_at else None
                    ),
                    "percentage": (
                        round((bin_obj.remaining / bin_obj.capacity) * 100, 1)
                        if bin_obj.capacity and bin_obj.remaining
                        else 0
                    ),
                }
            )

        return jsonify(
            {
                "ok": True,
                "device": {"id": device.id, "device_no": device.device_no, "model": device.model},
                "bins": bin_list,
            }
        )

    except Exception as e:
        return jsonify({"ok": False, "message": f"查询失败: {str(e)}"}), 500


@bp.route("/api/devices/<int:device_id>/bins", methods=["POST"])
@jwt_required(optional=True)
def create_device_bin(device_id: int):
    """为设备添加新料盒"""
    claims = _current_claims()
    error = _require_write(claims)
    if error:
        return jsonify({"ok": False, "message": error[0]}), error[1]

    try:
        # 权限检查
        device = Device.query.get(device_id)
        if not device:
            return jsonify({"ok": False, "message": "设备不存在"}), 404

        role = claims.get("role")
        merchant_id = claims.get("merchant_id")
        if role != "superadmin" and merchant_id and device.merchant_id != int(merchant_id):
            return jsonify({"ok": False, "message": "无权限访问此设备"}), 403

        data = request.get_json(force=True) or {}
        bin_index = int(data.get("bin_index", 0))

        if bin_index <= 0:
            return jsonify({"ok": False, "message": "料盒编号必须大于0"}), 400

        # 检查料盒是否已存在
        existing_bin = DeviceBin.query.filter_by(device_id=device_id, bin_index=bin_index).first()
        if existing_bin:
            return jsonify({"ok": False, "message": f"料盒 {bin_index} 已存在"}), 400

        # 创建新料盒
        new_bin = DeviceBin(
            device_id=device_id,
            bin_index=bin_index,
            material_id=data.get("material_id"),
            capacity=float(data.get("capacity", 100)),
            remaining=float(data.get("remaining", 0)),
            unit=data.get("unit", "g"),
            custom_label=data.get("custom_label", "").strip() or None,
        )

        db.session.add(new_bin)
        db.session.commit()

        return jsonify({"ok": True, "message": f"料盒 {bin_index} 创建成功"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": f"创建失败: {str(e)}"}), 500


@bp.route("/api/devices/<int:device_id>/bins/<int:bin_index>/bind", methods=["PUT"])
@jwt_required(optional=True)
def bind_device_bin_material(device_id: int, bin_index: int):
    """绑定料盒与物料"""
    claims = _current_claims()
    error = _require_write(claims)
    if error:
        return jsonify({"ok": False, "message": error[0]}), error[1]

    try:
        # 权限检查
        device = Device.query.get(device_id)
        if not device:
            return jsonify({"ok": False, "message": "设备不存在"}), 404

        role = claims.get("role")
        merchant_id = claims.get("merchant_id")
        if role != "superadmin" and merchant_id and device.merchant_id != int(merchant_id):
            return jsonify({"ok": False, "message": "无权限访问此设备"}), 403

        data = request.get_json(force=True) or {}
        material_id = data.get("material_id")

        # 验证物料存在
        if material_id:
            material = MaterialCatalog.query.filter_by(id=material_id, is_active=True).first()
            if not material:
                return jsonify({"ok": False, "message": "物料不存在或已禁用"}), 400

        # 获取或创建料盒
        bin_obj = DeviceBin.query.filter_by(device_id=device_id, bin_index=bin_index).first()
        if not bin_obj:
            # 创建新料盒
            bin_obj = DeviceBin(
                device_id=device_id, bin_index=bin_index, capacity=100, remaining=0, unit="g"
            )
            db.session.add(bin_obj)

        # 更新绑定
        bin_obj.material_id = material_id
        if material_id and material:
            # 使用物料的默认配置
            bin_obj.capacity = material.default_capacity
            bin_obj.unit = material.unit

        db.session.commit()

        return jsonify({"ok": True, "message": f"料盒 {bin_index} 绑定成功"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": f"绑定失败: {str(e)}"}), 500


@bp.route("/api/devices/bins/export")
@jwt_required(optional=True)
def export_device_bins():
    """导出所有设备料盒信息"""
    claims = _current_claims()
    if not claims:
        return jsonify({"ok": False, "message": "需要登录"}), 401

    try:
        # 权限过滤查询
        q = (
            db.session.query(DeviceBin, Device, MaterialCatalog)
            .join(Device, Device.id == DeviceBin.device_id)
            .outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceBin.material_id)
        )

        role = claims.get("role")
        merchant_id = claims.get("merchant_id")
        if role != "superadmin" and merchant_id:
            q = q.filter(Device.merchant_id == int(merchant_id))

        rows = q.order_by(Device.device_no.asc(), DeviceBin.bin_index.asc()).all()

        from ..utils.helpers import csv_response

        csv_rows = []
        for bin_obj, device, material in rows:
            percentage = (
                round((bin_obj.remaining / bin_obj.capacity) * 100, 1)
                if bin_obj.capacity and bin_obj.remaining
                else 0
            )
            csv_rows.append(
                [
                    device.device_no,
                    device.model or "",
                    bin_obj.bin_index,
                    material.name if material else "",
                    material.code if material else "",
                    material.category if material else "",
                    bin_obj.remaining or 0,
                    bin_obj.capacity or 0,
                    percentage,
                    bin_obj.unit or "g",
                    bin_obj.custom_label or "",
                    bin_obj.last_sync_at.isoformat() if bin_obj.last_sync_at else "",
                ]
            )

        # 记录导出操作
        try:
            db.session.add(
                OperationLog(
                    user_id=claims.get("id"),
                    action="export",
                    target_type="device_bins",
                    target_id=None,
                    ip=request.remote_addr,
                    user_agent=request.user_agent.string[:500] if request.user_agent else None,
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

        return csv_response(
            [
                "device_no",
                "device_model",
                "bin_index",
                "material_name",
                "material_code",
                "material_category",
                "remaining",
                "capacity",
                "percentage",
                "unit",
                "custom_label",
                "last_sync_at",
            ],
            csv_rows,
            filename="device_bins.csv",
        )

    except Exception as e:
        return jsonify({"ok": False, "message": f"导出失败: {str(e)}"}), 500


@bp.route("/api/materials/inventory")
@jwt_required(optional=True)
def list_materials_inventory():
    """获取物料库存列表，用于物料管理页面显示"""
    claims = _current_claims()
    if not claims:
        return jsonify({"ok": False, "message": "需要登录"}), 401

    try:
        # 分页参数
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 20))))

        # 筛选参数
        device_id = request.args.get("device_id")
        material_type = request.args.get("type")
        status = request.args.get("status")  # low/normal/empty

        # 构建查询
        query = (
            db.session.query(
                DeviceBin,
                Device.device_no,
                Device.model,
                Device.status.label("device_status"),
                MaterialCatalog.code,
                MaterialCatalog.name,
                MaterialCatalog.category,
            )
            .join(Device, Device.id == DeviceBin.device_id)
            .outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceBin.material_id)
        )

        # 商户权限过滤
        if claims.get("role") != "superadmin":
            merchant_id = claims.get("merchant_id")
            if merchant_id:
                query = query.filter(Device.merchant_id == merchant_id)

        # 设备筛选
        if device_id:
            query = query.filter(DeviceBin.device_id == device_id)

        # 物料类型筛选
        if material_type:
            query = query.filter(MaterialCatalog.category == material_type)

        # 库存状态筛选
        if status == "empty":
            query = query.filter(DeviceBin.remaining <= 0)
        elif status == "low":
            query = query.filter(
                DeviceBin.remaining > 0,
                DeviceBin.remaining < DeviceBin.capacity * 0.2,
                DeviceBin.capacity > 0,
            )
        elif status == "normal":
            query = query.filter(DeviceBin.remaining >= DeviceBin.capacity * 0.2)

        # 分页查询
        total = query.count()
        items = (
            query.order_by(Device.device_no, DeviceBin.bin_index)
            .limit(per_page)
            .offset((page - 1) * per_page)
            .all()
        )

        # 格式化结果
        inventory_items = []
        for (
            bin_obj,
            device_no,
            device_model,
            device_status,
            material_code,
            material_name,
            material_category,
        ) in items:
            # 确保数值字段不为None
            remaining = float(bin_obj.remaining) if bin_obj.remaining is not None else 0.0
            capacity = float(bin_obj.capacity) if bin_obj.capacity is not None else 0.0

            percentage = 0
            if capacity > 0:
                percentage = round((remaining / capacity) * 100, 1)

            # 确定库存状态
            if remaining <= 0:
                stock_status = "empty"
            elif percentage < 20:
                stock_status = "low"
            else:
                stock_status = "normal"

            inventory_items.append(
                {
                    "id": bin_obj.id,
                    "device_id": bin_obj.device_id,
                    "device_no": device_no,
                    "device_model": device_model,
                    "device_status": device_status,
                    "bin_index": bin_obj.bin_index,
                    "material_id": bin_obj.material_id,
                    "material_code": material_code or "",
                    "material_name": material_name or "未绑定物料",
                    "material_category": material_category or "",
                    "remaining": remaining,
                    "capacity": capacity,
                    "percentage": percentage,
                    "unit": bin_obj.unit or "",
                    "custom_label": bin_obj.custom_label or "",
                    "stock_status": stock_status,
                    "last_sync_at": (
                        bin_obj.last_sync_at.isoformat() if bin_obj.last_sync_at else None
                    ),
                }
            )

        return jsonify(
            {
                "ok": True,
                "data": {
                    "items": inventory_items,
                    "pagination": {
                        "page": page,
                        "per_page": per_page,
                        "total": total,
                        "pages": (total + per_page - 1) // per_page,
                    },
                },
            }
        )

    except Exception as e:
        return jsonify({"ok": False, "message": f"获取库存数据失败: {str(e)}"}), 500


@bp.route("/api/materials/export")
@jwt_required(optional=True)
def export_materials_inventory():
    """导出物料库存数据"""
    claims = _current_claims()
    if not claims:
        return jsonify({"ok": False, "message": "需要登录"}), 401

    try:
        from ..utils.helpers import csv_response

        # 使用相同的查询逻辑但不分页
        query = (
            db.session.query(
                DeviceBin,
                Device.device_no,
                Device.model,
                Device.status.label("device_status"),
                MaterialCatalog.code,
                MaterialCatalog.name,
                MaterialCatalog.category,
            )
            .join(Device, Device.id == DeviceBin.device_id)
            .outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceBin.material_id)
        )

        # 商户权限过滤
        if claims.get("role") != "superadmin":
            merchant_id = claims.get("merchant_id")
            if merchant_id:
                query = query.filter(Device.merchant_id == merchant_id)

        items = query.order_by(Device.device_no, DeviceBin.bin_index).all()

        # 格式化CSV数据
        csv_rows = []
        for (
            bin_obj,
            device_no,
            device_model,
            device_status,
            material_code,
            material_name,
            material_category,
        ) in items:
            percentage = 0
            if bin_obj.capacity and bin_obj.capacity > 0:
                percentage = round((bin_obj.remaining / bin_obj.capacity) * 100, 1)

            stock_status = (
                "empty" if bin_obj.remaining <= 0 else ("low" if percentage < 20 else "normal")
            )

            csv_rows.append(
                [
                    device_no,
                    device_model or "",
                    device_status,
                    bin_obj.bin_index,
                    material_code or "",
                    material_name or "未绑定物料",
                    material_category or "",
                    bin_obj.remaining,
                    bin_obj.capacity,
                    f"{percentage}%",
                    bin_obj.unit or "",
                    bin_obj.custom_label or "",
                    stock_status,
                    (
                        bin_obj.last_sync_at.strftime("%Y-%m-%d %H:%M:%S")
                        if bin_obj.last_sync_at
                        else ""
                    ),
                ]
            )

        return csv_response(
            [
                "设备编号",
                "设备型号",
                "设备状态",
                "料盒编号",
                "物料编码",
                "物料名称",
                "物料分类",
                "剩余量",
                "容量",
                "百分比",
                "单位",
                "自定义标签",
                "库存状态",
                "最后同步时间",
            ],
            csv_rows,
            filename="materials_inventory.csv",
        )

    except Exception as e:
        return jsonify({"ok": False, "message": f"导出失败: {str(e)}"}), 500
