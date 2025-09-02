"""Swagger UI 文档蓝图（flasgger）。"""
from __future__ import annotations
from flask import Blueprint, jsonify, redirect

bp = Blueprint("api_docs", __name__)


@bp.route("/api/docs")
def docs_index():
    # 重定向到 flasgger 的 UI
    return redirect("/apidocs")
