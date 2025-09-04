"""应用配置。
可通过环境变量覆盖，默认使用 SQLite 本地文件。
"""
from __future__ import annotations
import os
from datetime import timedelta
from pathlib import Path


class Config:
    BASE_DIR: Path = Path(__file__).resolve().parent.parent  # 项目根目录
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret")
    JWT_SECRET_KEY: str = os.environ.get("JWT_SECRET", "dev-jwt-secret")
    DATA_DIR: str = os.environ.get("DATA_DIR", str((BASE_DIR / "data").resolve()))
    # 绝对路径 SQLite，注意 Windows 需使用正斜杠
    _default_db_path = str((Path(DATA_DIR) / "db.sqlite").resolve()).replace("\\", "/")
    SQLALCHEMY_DATABASE_URI: str = os.environ.get("DATABASE_URL", f"sqlite:///{_default_db_path}")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    UPLOAD_FOLDER: str = os.environ.get("UPLOAD_FOLDER", str((BASE_DIR / "packages").resolve()))
    ALLOWED_EXTENSIONS: set[str] = {"zip", "tar", "gz", "json"}
    MAX_CONTENT_LENGTH: int = 100 * 1024 * 1024  # 100MB

    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=int(os.environ.get("JWT_ACCESS_MIN", "30")))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=int(os.environ.get("JWT_REFRESH_DAYS", "7")))

    MQTT_BROKER_URL: str | None = os.environ.get("MQTT_BROKER_URL")
    
    # Device registration
    DEVICE_REGISTRATION_KEY: str = os.environ.get("DEVICE_REGISTRATION_KEY", "default_registration_key")
    
    # Security features
    ENABLE_REQUEST_SIGNATURE: bool = os.environ.get("ENABLE_REQUEST_SIGNATURE", "false").lower() == "true"
    ENABLE_RATE_LIMITING: bool = os.environ.get("ENABLE_RATE_LIMITING", "true").lower() == "true"

    # Swagger
    SWAGGER = {
        "title": "咖啡机管理系统 API",
        "uiversion": 3,
        "openapi": "3.0.2",
    }

    # APScheduler
    SCHEDULER_API_ENABLED = True

    # Redis configuration
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    REDIS_DECODE_RESPONSES: bool = True
