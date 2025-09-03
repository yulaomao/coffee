"""安全与权限相关工具：密码散列、角色检查、商户过滤。"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from flask_jwt_extended import get_jwt, verify_jwt_in_request
from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(pw_hash: str, password: str) -> bool:
    return check_password_hash(pw_hash, password)


def require_roles(*roles: str) -> None:
    """在视图中调用以确保当前 JWT 拥有指定角色之一。"""
    verify_jwt_in_request()
    claims = get_jwt()
    user_role = claims.get("role")
    if user_role not in roles:
        from flask import abort

        abort(403, description="权限不足")


def merchant_scope_filter(query, user_claims: dict[str, Any]):
    """根据角色限制 merchant_id 范围。superadmin 不限制。"""
    role = user_claims.get("role")
    if role == "superadmin":
        return query
    merchant_id = user_claims.get("merchant_id")
    return query.filter_by(merchant_id=merchant_id)
