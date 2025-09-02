"""配方管理模块：CRUD、版本/包、下发与回执（最小可运行骨架）。"""
from __future__ import annotations
import io, os, json, uuid, zipfile, hashlib
from datetime import datetime
from typing import Any, List
from flask import Blueprint, jsonify, request, send_file, current_app, render_template, redirect, url_for
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..extensions import db
from ..models import User, Device, OperationLog, MaterialCatalog

bp = Blueprint("recipes", __name__)


# ========== 简化的数据表（使用已有 models.json 承载，后续可迁移至 SQLAlchemy 模型） ==========
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column
class Recipe(db.Model):
    __tablename__ = "recipes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False, index=True)
    version: Mapped[str] = mapped_column(nullable=True, index=True)
    description: Mapped[str] = mapped_column(nullable=True)
    author_id: Mapped[int] = mapped_column(nullable=True, index=True)
    status: Mapped[str] = mapped_column(nullable=False, default="draft", index=True)
    applicable_models: Mapped[Any] = mapped_column(JSON, nullable=True)
    bin_mapping_schema: Mapped[Any] = mapped_column(JSON, nullable=True)
    steps: Mapped[Any] = mapped_column(JSON, nullable=True)
    # 使用属性名 meta，底层列仍然叫 'metadata'，避免与 SQLAlchemy Declarative API 冲突
    meta: Mapped[Any] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class RecipePackage(db.Model):
    __tablename__ = "recipe_packages"
    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(nullable=False, index=True)
    package_name: Mapped[str] = mapped_column(nullable=False)
    package_path: Mapped[str] = mapped_column(nullable=False)
    md5: Mapped[str] = mapped_column(nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    uploaded_by: Mapped[int] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)


class RecipeDispatchBatch(db.Model):
    __tablename__ = "recipe_dispatch_batches"
    id: Mapped[str] = mapped_column(primary_key=True)  # uuid
    recipe_package_id: Mapped[int] = mapped_column(nullable=False, index=True)
    initiated_by: Mapped[int] = mapped_column(nullable=False, index=True)
    devices: Mapped[Any] = mapped_column(JSON, nullable=False)
    strategy: Mapped[str] = mapped_column(nullable=False, default="immediate")
    scheduled_time: Mapped[datetime | None] = mapped_column(nullable=True)
    status_summary: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)


class RecipeDispatchLog(db.Model):
    __tablename__ = "recipe_dispatch_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(nullable=False, index=True)
    command_id: Mapped[str] = mapped_column(nullable=False, index=True)
    status: Mapped[str] = mapped_column(nullable=False, default="pending")
    result_payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    result_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)


def _claims():
    try:
        return get_jwt_identity()
    except Exception:
        return None


def _current_claims():
    """JWT 优先；无 JWT 时从 session 取当前登录用户，返回 {id, role, merchant_id} 或 None。"""
    c = _claims()
    if c:
        return c
    try:
        from flask import session
        uid = session.get('user_id')
        if uid:
            u = User.query.get(uid)
            if u:
                return {"id": u.id, "role": u.role, "merchant_id": u.merchant_id}
    except Exception:
        pass
    return None


# ========== 前端页面 ==========
@bp.route("/recipes")
def recipes_page():
    return render_template("recipes.html")


@bp.route("/recipes/<int:rid>")
def recipe_detail_page(rid: int):
    r = Recipe.query.get_or_404(rid)
    return render_template("recipe_detail.html", recipe=r)


@bp.route("/recipes/packages")
def recipe_packages_page():
    # 页面已并入配方管理，这里做兼容性跳转
    return redirect(url_for('recipes.recipes_page'))


@bp.route("/recipes/<int:rid>/edit")
def recipe_edit_page(rid: int):
    r = Recipe.query.get_or_404(rid)
    # 机型选项（去重）与物料字典
    models = [m[0] for m in Device.query.with_entities(Device.model).distinct().all() if m[0]]
    materials = MaterialCatalog.query.order_by(MaterialCatalog.id.asc()).all()
    return render_template("recipe_edit.html", recipe=r, models_list=models, materials=materials)

@bp.route("/recipes/new")
def recipe_new_page():
    """创建一条空白草稿，预置一个默认步骤，并跳转到编辑页。"""
    u = _current_claims(); uid = u.get('id') if u else None
    default_step = [{"step_id":"s1","type":"grind","params":{"dose_g":7,"grind_time_ms":1200,"grind_level":3}}]
    r = Recipe(name=f"新配方-{datetime.utcnow().strftime('%H%M%S')}", description=None, author_id=uid,
               applicable_models=[], bin_mapping_schema={}, steps=default_step, meta={}, status='draft', version='v1.0.0')
    db.session.add(r); db.session.commit()
    return render_template("recipe_edit.html", recipe=r, models_list=[m[0] for m in Device.query.with_entities(Device.model).distinct().all() if m[0]], materials=MaterialCatalog.query.order_by(MaterialCatalog.id.asc()).all())


@bp.route("/recipes/dispatches/<string:batch_id>")
def recipe_dispatch_page(batch_id: str):
    return render_template("recipe_dispatch.html", batch_id=batch_id)


# ========== Schema ==========
@bp.route("/api/recipes/schema")
def recipe_schema():
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["name", "steps"],
        "properties": {
            "name": {"type": "string"},
            "version": {"type": "string"},
            "author": {"type": "string"},
            "applicable_models": {"type": "array", "items": {"type": "string"}},
            "bin_mapping": {"type": "object"},
            "steps": {"type": "array", "items": {"type": "object", "required":["type","params"], "properties":{
                "step_id": {"type": "string"},
                "type": {"type": "string"},
                "params": {"type": "object"}
            }}}
        }
    }
    return jsonify(schema)


# ========== CRUD ==========
@bp.route("/api/recipes")
@jwt_required(optional=True)
def list_recipes():
    # 可根据需要在此加入 merchant 过滤
    q = Recipe.query
    kw = request.args.get("q"); status = request.args.get("status"); model = request.args.get("model"); author = request.args.get("author")
    if kw: q = q.filter(Recipe.name.like(f"%{kw}%"))
    if status: q = q.filter(Recipe.status == status)
    if author: q = q.filter(Recipe.author_id == int(author))
    page = int(request.args.get("page", 1)); per_page = min(int(request.args.get("per_page", 20)), 100)
    total = q.count()
    items = q.order_by(Recipe.created_at.desc()).limit(per_page).offset((page-1)*per_page).all()
    # CSV 导出
    if (request.args.get('format') or '').lower() == 'csv':
        from ..utils.helpers import csv_response
        rows = [[r.id, r.name, r.version or '', r.status, r.author_id or '', r.created_at.isoformat()] for r in items]
        return csv_response(["id","name","version","status","author_id","created_at"], rows, filename="recipes.csv")
    return jsonify({
        "total": total, "page": page, "per_page": per_page,
        "items": [{
            "id": r.id, "name": r.name, "version": r.version, "status": r.status,
            "created_at": r.created_at.isoformat(), "author_id": r.author_id,
            "applicable_models": r.applicable_models or [], "products": 0
        } for r in items]
    })


@bp.route("/api/recipes/<int:rid>")
@jwt_required(optional=True)
def get_recipe(rid: int):
    r = Recipe.query.get_or_404(rid)
    # 历史版本（同名）
    versions = Recipe.query.filter(Recipe.name == r.name).order_by(Recipe.created_at.desc()).limit(20).all()
    return jsonify({
        "id": r.id, "name": r.name, "version": r.version, "description": r.description,
        "status": r.status, "author_id": r.author_id, "applicable_models": r.applicable_models or [],
        "bin_mapping_schema": r.bin_mapping_schema or {}, "steps": r.steps or [],
    "metadata": r.meta or {}, "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(),
        "versions": [{"id": v.id, "version": v.version, "created_at": v.created_at.isoformat()} for v in versions]
    })


@bp.route("/api/recipes", methods=["POST"])
@jwt_required(optional=True)
def create_recipe():
    data = request.get_json(force=True) or {}
    u = _current_claims(); uid = u.get('id') if u else None
    r = Recipe(name=data.get('name'), description=data.get('description'), author_id=uid,
               applicable_models=data.get('applicable_models'), bin_mapping_schema=data.get('bin_mapping_schema'),
               steps=data.get('steps'), meta=data.get('metadata'), status='draft', version=data.get('version') or 'v1.0.0')
    db.session.add(r); db.session.commit()
    try:
        db.session.add(OperationLog(user_id=uid or 0, action='recipe_create', target_type='recipe', target_id=r.id, ip=None, user_agent=None)); db.session.commit()
    except Exception: db.session.rollback()
    return jsonify({"ok": True, "recipe_id": r.id})


@bp.route("/api/recipes/<int:rid>", methods=["PUT"])
@jwt_required(optional=True)
def update_recipe(rid: int):
    r = Recipe.query.get_or_404(rid)
    data = request.get_json(force=True) or {}
    for k in ["name","description","applicable_models","bin_mapping_schema","steps","metadata","version","status"]:
        if k in data:
            if k == "metadata":
                r.meta = data[k]
            else:
                setattr(r, k, data[k])
    db.session.commit()
    return jsonify({"ok": True})


def _make_recipe_package(recipe: Recipe, uploader_id: int | None) -> RecipePackage:
    # 标准化 JSON
    payload = {
        "name": recipe.name,
        "version": recipe.version,
        "author": str(recipe.author_id or ""),
        "applicable_models": recipe.applicable_models or [],
        "bin_mapping": recipe.bin_mapping_schema or {},
        "steps": recipe.steps or [],
    "estimated_time_s": (recipe.meta or {}).get("estimated_time_s")
    }
    # 打包 ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('recipe.json', json.dumps(payload, ensure_ascii=False, indent=2))
        z.writestr('manifest.json', json.dumps({"name": recipe.name, "version": recipe.version, "created_at": datetime.utcnow().isoformat()}, ensure_ascii=False))
        z.writestr('readme.md', f"Recipe {recipe.name} {recipe.version}\n")
    data = buf.getvalue()
    md5 = hashlib.md5(data).hexdigest()
    pkg_dir = os.path.join(current_app.root_path, '..', 'packages', 'recipes')
    os.makedirs(pkg_dir, exist_ok=True)
    file_name = f"recipe_{recipe.id}_{recipe.version.replace('.', '_')}.zip"
    path = os.path.abspath(os.path.join(pkg_dir, file_name))
    with open(path, 'wb') as f: f.write(data)
    pkg = RecipePackage(recipe_id=recipe.id, package_name=file_name, package_path=path, md5=md5, size_bytes=len(data), uploaded_by=uploader_id)
    db.session.add(pkg); db.session.commit()
    return pkg


@bp.route("/api/recipes/<int:rid>/publish", methods=["POST"])
@jwt_required(optional=True)
def publish_recipe(rid: int):
    r = Recipe.query.get_or_404(rid)
    u = _current_claims(); uid = u.get('id') if u else None
    # 版本唯一性校验（同名+同版本不可重复）
    dup = Recipe.query.filter(Recipe.name == r.name, Recipe.version == r.version, Recipe.id != r.id).first()
    if dup:
        return jsonify({"ok": False, "message": "版本重复：相同名称与版本已存在"}), 400
    r.status = 'published'
    db.session.commit()
    pkg = _make_recipe_package(r, uid)
    try:
        db.session.add(OperationLog(user_id=uid or 0, action='recipe_publish', target_type='recipe', target_id=r.id, ip=None, user_agent=None)); db.session.commit()
    except Exception: db.session.rollback()
    return jsonify({"ok": True, "package_id": pkg.id, "md5": pkg.md5, "path": pkg.package_path})


@bp.route("/api/recipes/<int:rid>/package/download")
@jwt_required(optional=True)
def download_recipe_package(rid: int):
    pkg = RecipePackage.query.filter_by(recipe_id=rid).order_by(RecipePackage.created_at.desc()).first_or_404()
    return send_file(pkg.package_path, as_attachment=True, download_name=pkg.package_name)


@bp.route("/api/recipes/packages/upload", methods=["POST"])
@jwt_required(optional=True)
def upload_recipe_package():
    file = request.files.get('file')
    if not file:
        return jsonify({"ok": False, "message": "no file"}), 400
    data = file.read()
    md5 = hashlib.md5(data).hexdigest()
    # 简要解析 json/zip
    name = file.filename or 'recipe.zip'
    pkg_dir = os.path.join(current_app.root_path, '..', 'packages', 'recipes')
    os.makedirs(pkg_dir, exist_ok=True)
    path = os.path.abspath(os.path.join(pkg_dir, name))
    with open(path, 'wb') as f: f.write(data)
    rp = RecipePackage(recipe_id=0, package_name=name, package_path=path, md5=md5, size_bytes=len(data), uploaded_by=(_current_claims() or {}).get('id'))
    db.session.add(rp); db.session.commit()
    return jsonify({"ok": True, "package_id": rp.id, "md5": md5})

@bp.route("/api/recipes/<int:rid>/packages", methods=["GET"])
@jwt_required(optional=True)
def list_packages_by_recipe(rid: int):
    q = RecipePackage.query.filter_by(recipe_id=rid).order_by(RecipePackage.created_at.desc()).all()
    return jsonify({
        "items": [{
            "id": p.id, "recipe_id": p.recipe_id, "package_name": p.package_name, "md5": p.md5,
            "size_bytes": p.size_bytes, "created_at": p.created_at.isoformat()
        } for p in q]
    })

@bp.route("/api/recipes/<int:rid>/packages/upload", methods=["POST"])
@jwt_required(optional=True)
def upload_recipe_package_for_recipe(rid: int):
    file = request.files.get('file')
    if not file:
        return jsonify({"ok": False, "message": "no file"}), 400
    data = file.read()
    md5 = hashlib.md5(data).hexdigest()
    name = file.filename or f'recipe_{rid}.zip'
    pkg_dir = os.path.join(current_app.root_path, '..', 'packages', 'recipes')
    os.makedirs(pkg_dir, exist_ok=True)
    path = os.path.abspath(os.path.join(pkg_dir, name))
    with open(path, 'wb') as f: f.write(data)
    rp = RecipePackage(recipe_id=rid, package_name=name, package_path=path, md5=md5, size_bytes=len(data), uploaded_by=(_current_claims() or {}).get('id'))
    db.session.add(rp); db.session.commit()
    return jsonify({"ok": True, "package_id": rp.id, "md5": md5})


# ========== 下发 ==========
@bp.route("/api/recipes/packages/<int:package_id>/dispatch", methods=["POST"])
@jwt_required(optional=True)
def dispatch_package(package_id: int):
    data = request.get_json(force=True) or {}
    device_ids: List[int] = data.get('device_ids') or []
    strategy = data.get('strategy') or 'immediate'
    if not device_ids:
        return jsonify({"ok": False, "message": "empty devices"}), 400
    # 生成批次
    bid = str(uuid.uuid4())
    u = _current_claims(); uid = u.get('id') if u else None
    batch = RecipeDispatchBatch(id=bid, recipe_package_id=package_id, initiated_by=uid or 0, devices=device_ids, strategy=strategy, status_summary={"total": len(device_ids), "pending": len(device_ids)})
    db.session.add(batch); db.session.commit()
    # 逐台创建日志（pending）
    for did in device_ids:
        db.session.add(RecipeDispatchLog(batch_id=bid, device_id=did, command_id=str(uuid.uuid4()), status='pending'))
    db.session.commit()
    try:
        db.session.add(OperationLog(user_id=uid or 0, action='recipe_dispatch', target_type='recipe_batch', target_id=None, ip=None, user_agent=None)); db.session.commit()
    except Exception: db.session.rollback()
    return jsonify({"ok": True, "batch_id": bid})


@bp.route("/api/recipes/dispatches/<string:batch_id>")
@jwt_required(optional=True)
def dispatch_detail(batch_id: str):
    b = RecipeDispatchBatch.query.get_or_404(batch_id)
    logs = RecipeDispatchLog.query.filter_by(batch_id=batch_id).order_by(RecipeDispatchLog.created_at.desc()).all()
    return jsonify({
        "batch": {"id": b.id, "strategy": b.strategy, "devices": b.devices, "status_summary": b.status_summary, "created_at": b.created_at.isoformat()},
        "logs": [{"device_id": l.device_id, "status": l.status, "command_id": l.command_id, "result_at": l.result_at.isoformat() if l.result_at else None} for l in logs]
    })


@bp.route("/api/recipes/packages/<int:pid>/download")
@jwt_required(optional=True)
def download_package_by_id(pid: int):
    p = RecipePackage.query.get_or_404(pid)
    return send_file(p.package_path, as_attachment=True, download_name=p.package_name)

@bp.route("/api/recipes/packages/<int:pid>", methods=["DELETE"])
@jwt_required(optional=True)
def delete_package_by_id(pid: int):
    p = RecipePackage.query.get_or_404(pid)
    # 尝试删除文件
    try:
        if p.package_path and os.path.exists(p.package_path):
            os.remove(p.package_path)
    except Exception:
        pass
    db.session.delete(p)
    db.session.commit()
    try:
        u = _current_claims(); uid = (u or {}).get('id') or 0
        db.session.add(OperationLog(user_id=uid, action='recipe_package_delete', target_type='recipe_package', target_id=pid, ip=None, user_agent=None)); db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify({"ok": True})


@bp.route("/api/devices/<int:device_id>/recipes/command_result", methods=["POST"])
def recipe_command_result(device_id: int):
    data = request.get_json(force=True) or {}
    cmd_id = data.get('command_id'); status = data.get('status'); payload = data.get('payload')
    log = RecipeDispatchLog.query.filter_by(device_id=device_id, command_id=cmd_id).order_by(RecipeDispatchLog.created_at.desc()).first()
    if not log:
        return jsonify({"ok": False, "message": "not found"}), 404
    log.status = status or log.status
    log.result_payload = payload
    log.result_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True})

# ========== 包列表 ==========
@bp.route("/api/recipes/packages")
@jwt_required(optional=True)
def list_packages():
    q = RecipePackage.query.order_by(RecipePackage.created_at.desc()).limit(200).all()
    return jsonify({
        "items": [{
            "id": p.id, "recipe_id": p.recipe_id, "package_name": p.package_name, "md5": p.md5,
            "size_bytes": p.size_bytes, "created_at": p.created_at.isoformat()
        } for p in q]
    })
