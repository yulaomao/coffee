"""Flask 扩展集中初始化。"""
from __future__ import annotations
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flasgger import Swagger
from apscheduler.schedulers.background import BackgroundScheduler

# 全局扩展实例

db: SQLAlchemy = SQLAlchemy()
migrate: Migrate = Migrate()
jwt: JWTManager = JWTManager()
swagger: Swagger = Swagger()
scheduler: BackgroundScheduler = BackgroundScheduler()
