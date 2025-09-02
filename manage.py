"""
manage.py - 应用入口与开发运行脚本。
可通过 `python manage.py runserver` 启动。
"""
from __future__ import annotations
import os
from flask import Flask
from app import create_app

app: Flask = create_app()

if __name__ == "__main__":
    # 允许从环境覆盖端口
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_ENV") == "development")
