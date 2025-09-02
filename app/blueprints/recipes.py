"""配方包接口：
- POST /api/recipes/package 生成 JSON 到 packages/
"""
from __future__ import annotations
import json
import os
from datetime import datetime
from typing import Any
from flask import Blueprint, jsonify, current_app
from flask_jwt_extended import jwt_required

bp = Blueprint("recipes", __name__)


@bp.route("/api/recipes/package", methods=["POST"])
@jwt_required()
def build_recipe_package():
    # 最小实现：生成包含配方映射的 JSON 文件
    payload: dict[str, Any] = {
        "name": f"recipe-{datetime.utcnow().isoformat()}",
        "mapping": {"A": "coffee_powder", "B": "milk"},
    }
    os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], f"{payload['name']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return jsonify({"path": path})
