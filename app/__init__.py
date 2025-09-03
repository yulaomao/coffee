"""app 工厂与初始化逻辑。
最小可运行实现：注册扩展、蓝图、任务系统与调度。
"""
from __future__ import annotations
import os
from datetime import timedelta
from flask import Flask, render_template, redirect, url_for
from .config import Config
from .extensions import db, migrate, jwt, swagger, scheduler
from .models import User, Merchant
from .utils.security import hash_password
from .tasks.worker import start_background_worker


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=False, template_folder="templates", static_folder="static")

    # 基础配置
    app.config.from_object(Config())

    # 初始化扩展
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    swagger.init_app(app)
    
    # 初始化 WebSocket
    from .blueprints.websocket import init_socketio
    socketio = init_socketio(app)
    
    # 启动 APScheduler（BackgroundScheduler 无 init_app 方法）
    # 确保仅启动一次
    try:
        if not scheduler.running:
            scheduler.start()
    except Exception:
        # 某些情况下 running 属性不存在，直接尝试启动
        try:
            scheduler.start()
        except Exception:
            pass

    # 确保本地目录存在（使用绝对路径）
    data_dir = app.config.get("DATA_DIR")
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
    upload_dir = app.config.get("UPLOAD_FOLDER")
    if upload_dir:
        os.makedirs(upload_dir, exist_ok=True)

    # 数据库自动初始化（最小可运行版）
    with app.app_context():
        db.create_all()
        # 轻量 SQLite 架构升级：为旧库补齐新增列（开发/演示用）
        try:
            from .utils.upgrade import ensure_sqlite_schema
            ensure_sqlite_schema(db.engine)
        except Exception:
            pass
        # 若无用户则创建默认商户与管理员
        if not User.query.first():
            m = Merchant(name="默认商户")
            db.session.add(m)
            db.session.flush()
            admin = User(
                username="admin",
                password_hash=hash_password("admin123"),
                email="admin@example.com",
                role="superadmin",
                merchant_id=m.id,
            )
            db.session.add(admin)
            db.session.commit()
        # 启动自举：确保物料字典与料盒最小数据存在（幂等）
        try:
            from .utils.bootstrap import ensure_bootstrap_materials
            ensure_bootstrap_materials()
        except Exception:
            pass

    # 启动后台任务 worker
    start_background_worker(app)

    # 注册蓝图
    from .blueprints import auth, admin, devices, orders, materials, faults, upgrades, finance, operation_logs, recipes, simulate, api_docs, client_api
    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(devices.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(materials.bp)
    app.register_blueprint(faults.bp)
    app.register_blueprint(upgrades.bp)
    app.register_blueprint(finance.bp)
    app.register_blueprint(operation_logs.bp)
    app.register_blueprint(recipes.bp)
    app.register_blueprint(simulate.bp)
    app.register_blueprint(api_docs.bp)
    app.register_blueprint(client_api.bp)

    # JWT 回调：identity 直接是 dict（包含 id/role/merchant_id）
    @jwt.user_identity_loader
    def user_identity_lookup(identity):  # type: ignore[no-untyped-def]
        return identity

    # 首页重定向到登录或仪表盘
    @app.route("/")
    def index():
        # 始终重定向到登录页面，避免在根路径提交表单导致 405
        return redirect(url_for("auth.login_page"))

    # WebSocket测试页面
    @app.route("/websocket-test")
    def websocket_test():
        return render_template("websocket_test.html")

    # 将socketio实例附加到app以便在其他地方使用
    app.socketio = socketio

    return app
