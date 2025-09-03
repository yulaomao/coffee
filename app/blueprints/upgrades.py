"""升级/包管理 API：
- POST /api/upgrades (multipart upload)
- POST /api/upgrades/dispatch
"""

from __future__ import annotations

import os
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import Device, RemoteCommand, UpgradePackage
from ..tasks.queue import Task, submit_task
from ..utils.helpers import allowed_file, file_md5

bp = Blueprint("upgrades", __name__)


@bp.route("/api/upgrades", methods=["POST"])
@jwt_required()
def upload_upgrade():
    if "file" not in request.files:
        return jsonify({"msg": "缺少文件"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"msg": "文件名为空"}), 400
    if not allowed_file(f.filename):
        return jsonify({"msg": "不允许的文件类型"}), 400
    os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
    filename = secure_filename(f.filename)
    save_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    f.save(save_path)
    md5 = file_md5(save_path)
    pkg = UpgradePackage(
        version=request.form.get("version", "v1"), file_name=filename, file_path=save_path, md5=md5
    )
    db.session.add(pkg)
    db.session.commit()
    return jsonify({"id": pkg.id, "md5": md5})


@bp.route("/api/upgrades/dispatch", methods=["POST"])
@jwt_required()
def dispatch_upgrade():
    data: dict[str, Any] = request.get_json(force=True)
    device_ids = data.get("device_ids", [])
    package_id = data.get("package_id")
    if not device_ids or not package_id:
        return jsonify({"msg": "device_ids 与 package_id 必填"}), 400
    cmds = []
    for did in device_ids:
        dev = Device.query.get(did)
        if not dev:
            continue
        rc = RemoteCommand(
            command_id=os.urandom(8).hex(),
            device_id=dev.id,
            command_type="upgrade",
            payload={"package_id": package_id},
            issued_by=0,
        )
        db.session.add(rc)
        cmds.append(rc.command_id)
        submit_task(
            Task(id=rc.command_id, type="dispatch_command", payload={"command_id": rc.command_id})
        )
    db.session.commit()
    return jsonify({"command_ids": cmds})
