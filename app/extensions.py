"""Flask 扩展集中初始化。"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from flasgger import Swagger
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# 全局扩展实例

db: SQLAlchemy = SQLAlchemy()
migrate: Migrate = Migrate()
jwt: JWTManager = JWTManager()
swagger: Swagger = Swagger()
scheduler: BackgroundScheduler = BackgroundScheduler()
