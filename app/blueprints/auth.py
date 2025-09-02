"""认证与会话蓝图：JWT 登录/刷新 + 页面登录。
API:
- POST /api/auth/login
- POST /api/auth/refresh
"""
from __future__ import annotations
from datetime import timedelta
from typing import Any, Optional
from flask import Blueprint, jsonify, request, render_template, redirect, url_for, session
from flask_jwt_extended import create_access_token, create_refresh_token, jwt_required, get_jwt_identity
from ..extensions import db
from ..models import User
from ..utils.security import verify_password

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        return render_template("login.html")
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    user = User.query.filter_by(username=username).first()
    if not user or not verify_password(user.password_hash, password):
        return render_template("login.html", error="用户名或密码错误"), 401
    # 简单会话：记录 user_id
    session["user_id"] = user.id
    return redirect(url_for("admin.dashboard"))


@bp.route("/logout")
def logout_page():
    session.clear()
    return redirect(url_for("auth.login_page"))


@bp.route("/api/auth/login", methods=["POST"])
def api_login():
    data: dict[str, Any] = request.get_json(force=True)
    username = data.get("username", "")
    password = data.get("password", "")
    user = User.query.filter_by(username=username).first()
    if not user or not verify_password(user.password_hash, password):
        return jsonify({"msg": "用户名或密码错误"}), 401
    identity = {"id": user.id, "role": user.role, "merchant_id": user.merchant_id}
    access_token = create_access_token(identity=identity)
    refresh_token = create_refresh_token(identity=identity)
    return jsonify({"access_token": access_token, "refresh_token": refresh_token})


@bp.route("/api/auth/refresh", methods=["POST"])
@jwt_required(refresh=True)
def api_refresh():
    identity = get_jwt_identity()
    access_token = create_access_token(identity=identity)
    return jsonify({"access_token": access_token})
