"""物料管理 API：
- 兼容保留：
    - GET/PUT /api/devices/<id>/materials（向后兼容，基于 DeviceBin 实现）
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
from ..models import Device, MaterialCatalog, User, OperationLog, DeviceBin, RemoteCommand
from ..extensions import db
from ..utils.security import merchant_scope_filter
from datetime import datetime
import csv
from io import StringIO

bp = Blueprint("materials", __name__)


@bp.route("/api/devices/<int:device_id>/materials", methods=["GET", "PUT"])
@jwt_required()
def device_materials(device_id: int):
    """设备物料接口，基于新的 DeviceBin 模型，保持向后兼容的 API 格式"""
    claims = get_jwt_identity() or {}
    
    # 权限检查
    role = claims.get('role'); mid = claims.get('merchant_id')
    if role != 'superadmin' and mid is not None:
        device = Device.query.filter_by(id=device_id, merchant_id=int(mid)).first()
        if not device:
            return jsonify({"ok": False, "message": "设备不存在或无权限"}), 404
    else:
        device = Device.query.get(device_id)
        if not device:
            return jsonify({"ok": False, "message": "设备不存在"}), 404
    
    if request.method == "GET":
        # 查询设备的料盒数据，转换为旧格式
        bins = DeviceBin.query.filter_by(device_id=device_id).all()
        fmt = request.args.get('format')
        
        if fmt == 'csv':
            from ..utils.helpers import csv_response
            rows = [[
                bin.bin_index, 
                bin.material_id or 0, 
                bin.remaining or 0.0, 
                bin.capacity or 0.0, 
                10.0  # 默认阈值，因为 DeviceBin 没有 threshold 字段
            ] for bin in bins]
            return csv_response(["bin_id","material_id","remain","capacity","threshold"], 
                              rows, filename=f"device_{device_id}_materials.csv")
        
        # JSON 格式，保持向后兼容
        items = []
        for bin in bins:
            items.append({
                "id": bin.bin_index,  # 使用 bin_index 作为 ID
                "material_id": bin.material_id or 0,
                "remain": bin.remaining or 0.0,
                "capacity": bin.capacity or 0.0,
                "threshold": 10.0  # 默认阈值
            })
        
        return jsonify({"items": items})
    
    else:  # PUT
        data: dict[str, Any] = request.get_json(force=True)
        
        for item in data.get("items", []):
            # 查找对应的料盒（通过 material_id 匹配）
            material_id = item.get("material_id")
            if material_id:
                bin = DeviceBin.query.filter_by(device_id=device_id, material_id=material_id).first()
                if bin:
                    # 更新余量和容量
                    if "remain" in item:
                        bin.remaining = float(item["remain"])
                    if "capacity" in item:
                        bin.capacity = float(item["capacity"])
                    # threshold 在 DeviceBin 中不存在，跳过
        
        db.session.commit()
        return jsonify({"msg": "updated"})


def _materials_base_query(claims):
    """构建物料查询基础，统一使用 DeviceBin + MaterialCatalog 模式"""
    q = db.session.query(
        Device.device_no.label('device_no'),
        Device.model.label('device_name'),
        DeviceBin.bin_index.label('bin_id'),
        MaterialCatalog.name.label('material_name'),
        MaterialCatalog.category.label('material_type'),
        DeviceBin.remaining.label('remain'),
        DeviceBin.capacity.label('capacity'),
        DeviceBin.last_sync_at.label('updated_at'),
        DeviceBin.unit.label('unit'),
    ).select_from(DeviceBin)
    q = q.join(Device, Device.id == DeviceBin.device_id)
    q = q.outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceBin.material_id)
    
    # 权限过滤：superadmin 不限制，其他角色按 merchant_id 过滤
    if claims:
        role = claims.get('role')
        merchant_id = claims.get('merchant_id')
        if role != 'superadmin' and merchant_id:
            try:
                q = q.filter(Device.merchant_id == int(merchant_id))
            except (ValueError, TypeError):
                # 无效 merchant_id，返回空结果
                q = q.filter(False)
    return q


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
    user_id = session.get('user_id')
    if user_id:
        try:
            user = User.query.get(int(user_id))
            if user:
                return {
                    "id": user.id, 
                    "role": user.role, 
                    "merchant_id": user.merchant_id
                }
        except Exception:
            pass
    
    return None


def _require_write(claims) -> Optional[tuple[str, int]]:
    """检查写操作权限"""
    if not claims:
        return ("未授权：需要登录", 401)
    
    role = claims.get('role')
    if role not in {"superadmin", "merchant_admin", "ops_engineer"}:
        return ("权限不足：需要管理员权限", 403)
    
    return None


def _validate_material_data(data: dict) -> Optional[str]:
    """验证物料数据的完整性和合法性"""
    if not data.get('name', '').strip():
        return "物料名称不能为空"
    
    unit = data.get('unit', '').strip()
    if unit and unit not in ['g', 'ml', 'pcs', '个', '包', 'kg', 'l']:
        return "单位必须是: g, ml, pcs, 个, 包, kg, l 之一"
    
    try:
        if data.get('default_capacity') is not None:
            capacity = float(data['default_capacity'])
            if capacity <= 0:
                return "默认容量必须大于0"
    except (ValueError, TypeError):
        return "默认容量必须是有效数字"
    
    return None


# -------------------- 物料字典（Material Catalog） --------------------

@bp.route("/api/material_catalog", methods=["GET", "POST"])
@jwt_required(optional=True)
def material_catalog_list_create():
    claims = _current_claims()
    
    if request.method == "GET":
        q = MaterialCatalog.query.filter(MaterialCatalog.is_active == True)  # 只显示活跃物料
        
        # 筛选参数
        keyword = request.args.get('name') or request.args.get('q', '').strip()
        category = request.args.get('category', '').strip()
        code = request.args.get('code', '').strip()
        
        if keyword:
            like_pattern = f"%{keyword}%"
            q = q.filter(
                (MaterialCatalog.name.like(like_pattern)) | 
                (MaterialCatalog.code.like(like_pattern))
            )
        if category:
            q = q.filter(MaterialCatalog.category == category)
        if code:
            q = q.filter(MaterialCatalog.code == code)
        
        # 分页
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(200, max(1, int(request.args.get('per_page', 20))))
        total = q.count()
        
        rows = q.order_by(MaterialCatalog.created_at.desc()).limit(per_page).offset((page-1)*per_page).all()
        
        return jsonify({
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
                    "is_active": m.is_active
                } for m in rows
            ]
        })
    
    # POST - 创建新物料
    err = _require_write(claims)
    if err: 
        return jsonify({"ok": False, "message": err[0]}), err[1]
    
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "message": "无效的JSON数据"}), 400
    
    # 验证数据
    validation_error = _validate_material_data(data)
    if validation_error:
        return jsonify({"ok": False, "message": validation_error}), 400
    
    # 检查编码唯一性
    code = (data.get('code') or '').strip() or None
    if code and MaterialCatalog.query.filter_by(code=code).first():
        return jsonify({"ok": False, "message": f"编码 '{code}' 已存在"}), 400
    
    # 检查名称唯一性
    name = data['name'].strip()
    if MaterialCatalog.query.filter_by(name=name).first():
        return jsonify({"ok": False, "message": f"物料名称 '{name}' 已存在"}), 400
    
    try:
        material = MaterialCatalog(
            code=code,
            name=name,
            category=data.get('category', '').strip() or None,
            unit=data.get('unit', 'g').strip(),
            default_capacity=float(data['default_capacity']) if data.get('default_capacity') else None,
            description=data.get('description', '').strip() or None,
            created_by=claims.get('id') if claims else None,
            is_active=True,
        )
        
        db.session.add(material)
        db.session.flush()  # 获取ID
        
        # 记录操作日志
        log_entry = OperationLog(
            user_id=claims.get('id') if claims else None, 
            action='material_create', 
            target_type='material_catalog', 
            target_id=material.id,
            ip=request.remote_addr,
            user_agent=request.headers.get('User-Agent', ''),
            raw_payload=data
        )
        db.session.add(log_entry)
        db.session.commit()
        
        return jsonify({
            "ok": True, 
            "message": "物料创建成功",
            "data": {"id": material.id}
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": f"创建失败: {str(e)}"}), 500


@bp.route("/api/material_catalog/<int:mid>", methods=["GET", "PUT", "DELETE"])
@jwt_required(optional=True)
def material_catalog_detail(mid: int):
    claims = _current_claims()
    
    try:
        material = MaterialCatalog.query.get_or_404(mid)
    except Exception:
        return jsonify({"ok": False, "message": "物料不存在"}), 404
    
    if request.method == "GET":
        return jsonify({
            "ok": True, 
            "data": {
                "id": material.id, 
                "code": material.code, 
                "name": material.name, 
                "category": material.category, 
                "unit": material.unit,
                "default_capacity": material.default_capacity, 
                "description": material.description, 
                "is_active": material.is_active,
                "created_at": material.created_at.isoformat() if material.created_at else None,
                "updated_at": material.updated_at.isoformat() if material.updated_at else None
            }
        })
    
    # PUT/DELETE 需要写权限
    err = _require_write(claims)
    if err: 
        return jsonify({"ok": False, "message": err[0]}), err[1]
    
    if request.method == "PUT":
        try:
            data = request.get_json(force=True) or {}
        except Exception:
            return jsonify({"ok": False, "message": "无效的JSON数据"}), 400
        
        # 验证数据
        validation_error = _validate_material_data(data)
        if validation_error:
            return jsonify({"ok": False, "message": validation_error}), 400
        
        # 检查编码唯一性（如果更改了编码）
        new_code = (data.get('code') or '').strip() or None
        if new_code and new_code != material.code:
            existing = MaterialCatalog.query.filter_by(code=new_code).first()
            if existing:
                return jsonify({"ok": False, "message": f"编码 '{new_code}' 已被其他物料使用"}), 400
        
        # 检查名称唯一性（如果更改了名称）
        new_name = data['name'].strip()
        if new_name != material.name:
            existing = MaterialCatalog.query.filter_by(name=new_name).first()
            if existing:
                return jsonify({"ok": False, "message": f"物料名称 '{new_name}' 已被其他物料使用"}), 400
        
        try:
            # 更新物料信息
            updatable_fields = ["code", "name", "category", "unit", "default_capacity", "description", "is_active"]
            for field in updatable_fields:
                if field in data:
                    if field == 'default_capacity':
                        value = float(data[field]) if data[field] is not None else None
                    elif field in ['code', 'category', 'description']:
                        value = (data[field] or '').strip() or None
                    elif field in ['name', 'unit']:
                        value = (data[field] or '').strip()
                    else:
                        value = data[field]
                    setattr(material, field, value)
            
            # 记录操作日志
            log_entry = OperationLog(
                user_id=claims.get('id') if claims else None, 
                action='material_update', 
                target_type='material_catalog', 
                target_id=material.id,
                ip=request.remote_addr,
                user_agent=request.headers.get('User-Agent', ''),
                raw_payload=data
            )
            db.session.add(log_entry)
            db.session.commit()
            
            return jsonify({"ok": True, "message": "物料更新成功"})
            
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "message": f"更新失败: {str(e)}"}), 500
    
    # DELETE - 软删除
    try:
        material.is_active = False
        
        log_entry = OperationLog(
            user_id=claims.get('id') if claims else None, 
            action='material_delete', 
            target_type='material_catalog', 
            target_id=material.id,
            ip=request.remote_addr,
            user_agent=request.headers.get('User-Agent', ''),
            raw_payload=None
        )
        db.session.add(log_entry)
        db.session.commit()
        
        return jsonify({"ok": True, "message": "物料已删除"})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": f"删除失败: {str(e)}"}), 500


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
    """获取或创建设备料盒，确保数据完整性"""
    if bin_index < 1:
        raise ValueError("料盒索引必须大于0")
    
    bin_obj = DeviceBin.query.filter_by(device_id=device_id, bin_index=bin_index).first()
    if not bin_obj:
        # 验证设备存在
        device = Device.query.get(device_id)
        if not device:
            raise ValueError(f"设备 ID {device_id} 不存在")
        
        bin_obj = DeviceBin(device_id=device_id, bin_index=bin_index)
        db.session.add(bin_obj)
        db.session.flush()  # 获取ID但不提交
    
    return bin_obj


def _validate_bin_operation(device_id: int, bin_index: int, claims: dict = None) -> Optional[tuple[str, int]]:
    """验证料盒操作的权限和合法性"""
    try:
        device = Device.query.get(device_id)
        if not device:
            return ("设备不存在", 404)
        
        if bin_index < 1 or bin_index > 20:  # 假设最多20个料盒
            return ("料盒索引必须在1-20之间", 400)
        
        # 权限检查
        if claims:
            role = claims.get('role')
            merchant_id = claims.get('merchant_id')
            if role != 'superadmin' and merchant_id != device.merchant_id:
                return ("无权限操作该设备的料盒", 403)
        
        return None
        
    except Exception:
        return ("验证失败", 500)


@bp.route("/api/devices/<int:device_id>/bins", methods=["GET", "POST"])
@jwt_required(optional=True)
def device_bins(device_id: int):
    claims = _current_claims()
    
    # 验证设备和权限
    validation_error = _validate_bin_operation(device_id, 1, claims)  # 使用索引1做基础验证
    if validation_error and validation_error[1] in [403, 404]:
        return jsonify({"ok": False, "message": validation_error[0]}), validation_error[1]
    
    if request.method == "GET":
        try:
            # 获取设备的所有料盒，连接物料信息
            query = db.session.query(DeviceBin, MaterialCatalog, Device).join(
                Device, Device.id == DeviceBin.device_id
            ).outerjoin(
                MaterialCatalog, MaterialCatalog.id == DeviceBin.material_id
            ).filter(DeviceBin.device_id == device_id)
            
            rows = query.order_by(DeviceBin.bin_index.asc()).all()
            
            bins = []
            for bin_obj, material, device in rows:
                # 计算容量：优先使用料盒自定义容量，其次物料默认容量
                capacity = bin_obj.capacity
                if capacity is None and material:
                    capacity = material.default_capacity
                
                bin_data = {
                    "device_id": device_id,
                    "bin_index": bin_obj.bin_index,
                    "material": (
                        {
                            "id": material.id, 
                            "code": material.code, 
                            "name": material.name, 
                            "unit": material.unit,
                            "category": material.category
                        } if material else None
                    ),
                    "capacity": capacity,
                    "remaining": bin_obj.remaining,
                    "unit": bin_obj.unit or (material.unit if material else None),
                    "last_sync_at": (bin_obj.last_sync_at.isoformat() if bin_obj.last_sync_at else None),
                    "custom_label": bin_obj.custom_label,
                    "utilization": None  # 计算使用率
                }
                
                # 计算使用率
                if capacity and bin_obj.remaining is not None:
                    bin_data["utilization"] = round((bin_obj.remaining / capacity) * 100, 1)
                
                bins.append(bin_data)
            
            return jsonify({"ok": True, "data": bins})
            
        except Exception as e:
            return jsonify({"ok": False, "message": f"获取料盒信息失败: {str(e)}"}), 500
    
    # POST - 初始化料盒
    err = _require_write(claims)
    if err: 
        return jsonify({"ok": False, "message": err[0]}), err[1]
    
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "message": "无效的JSON数据"}), 400
    
    bins_config = data.get('bins', [])
    if not bins_config or not isinstance(bins_config, list):
        return jsonify({"ok": False, "message": "bins参数必须是非空数组"}), 400
    
    try:
        created_count = 0
        for bin_config in bins_config:
            if not isinstance(bin_config, dict):
                continue
                
            bin_index = bin_config.get('bin_index')
            if not bin_index or bin_index < 1:
                continue
            
            # 验证料盒索引
            validation_error = _validate_bin_operation(device_id, bin_index, claims)
            if validation_error:
                continue
            
            bin_obj = _get_or_create_bin(device_id, bin_index)
            
            # 更新料盒配置
            if bin_config.get('capacity') is not None:
                try:
                    bin_obj.capacity = float(bin_config['capacity'])
                except (ValueError, TypeError):
                    continue
                    
            if bin_config.get('custom_label') is not None:
                bin_obj.custom_label = str(bin_config['custom_label']).strip() or None
            
            created_count += 1
        
        # 记录操作日志
        log_entry = OperationLog(
            user_id=claims.get('id') if claims else None, 
            action='device_bins_init', 
            target_type='device', 
            target_id=device_id,
            ip=request.remote_addr,
            user_agent=request.headers.get('User-Agent', ''),
            raw_payload={"bins_count": created_count}
        )
        db.session.add(log_entry)
        db.session.commit()
        
        return jsonify({
            "ok": True, 
            "message": f"成功初始化 {created_count} 个料盒",
            "data": {"initialized": created_count}
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "message": f"初始化失败: {str(e)}"}), 500


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
    """物料余量汇总列表（使用统一的 DeviceBin + MaterialCatalog 模式）"""
    claims = _current_claims()
    if not claims:
        return jsonify({"ok": False, "message": "需要登录"}), 401
    
    try:
        q = _materials_base_query(claims)
        
        # 筛选参数
        device_no = request.args.get('device_id') or request.args.get('device_no')
        material_type = request.args.get('type')
        name_keyword = request.args.get('name')
        
        if device_no:
            device_no = device_no.strip()
            if device_no:
                q = q.filter(Device.device_no.like(f"%{device_no}%"))
        
        if material_type:
            material_type = material_type.strip()
            if material_type:
                q = q.filter(
                    (MaterialCatalog.category == material_type) | 
                    (MaterialCatalog.name.like(f"%{material_type}%"))
                )
        
        if name_keyword:
            name_keyword = name_keyword.strip()
            if name_keyword:
                like_pattern = f"%{name_keyword}%"
                q = q.filter(
                    (MaterialCatalog.name.like(like_pattern)) | 
                    (Device.model.like(like_pattern))
                )
        
        # 分页
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(200, max(1, int(request.args.get('per_page', 20))))
        total = q.count()
        
        rows = q.order_by(
            Device.device_no.asc(), 
            DeviceBin.bin_index.asc()
        ).limit(per_page).offset((page-1)*per_page).all()
        
        items = []
        for row in rows:
            # 安全地获取数值，防止None值
            capacity = float(row.capacity or 0)
            remaining = float(row.remain or 0)
            percentage = round((remaining / capacity) * 100, 1) if capacity > 0 else 0
            
            # 判断库存状态
            status = "正常"
            if remaining <= 0:
                status = "空"
            elif percentage < 20:
                status = "低"
            elif percentage < 50:
                status = "中"
            
            items.append({
                "device_no": row.device_no,
                "device_name": row.device_name or "",
                "bin_id": row.bin_id,
                "material_name": row.material_name or f"料盒{row.bin_id}",
                "material_type": row.material_type or "-",
                "remain": remaining,
                "capacity": capacity,
                "percent": percentage,
                "unit": row.unit or "g",
                "status": status,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            })
        
        return jsonify({
            "ok": True,
            "total": total, 
            "page": page, 
            "per_page": per_page, 
            "items": items
        })
        
    except Exception as e:
        return jsonify({"ok": False, "message": f"查询失败: {str(e)}"}), 500


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
    rows = q.order_by(Device.device_no.asc(), DeviceBin.bin_index.asc()).all()
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
