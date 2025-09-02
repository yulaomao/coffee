"""分账/发票 API 框架（占位可运行）。
- GET/POST /api/finance/*
说明：保存记录与导出，第三方对接留空在 README 中说明。
"""
from __future__ import annotations
from typing import Any
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

bp = Blueprint("finance", __name__)


@bp.route("/api/finance/records", methods=["GET", "POST"])
@jwt_required()
def finance_records():
    # 最小实现：内存回传（演示），可扩展为数据库表
    if request.method == "POST":
        data: dict[str, Any] = request.get_json(force=True)
        return jsonify({"msg": "saved", "data": data})
    return jsonify({"items": []})
