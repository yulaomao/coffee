"""HTTP 模拟设备上报/回执，用于无 MQTT broker 的本地测试。
- POST /simulate/device/<device_no>/status
- POST /simulate/device/<device_no>/command_result
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request

from ..extensions import db
from ..models import CommandResult, Device, DeviceStatusLog, RemoteCommand

bp = Blueprint("simulate", __name__)


@bp.route("/simulate/device/<string:device_no>/status", methods=["POST"])
def sim_status(device_no: str):
    dev = Device.query.filter_by(device_no=device_no).first_or_404()
    payload = request.get_json(force=True)
    log = DeviceStatusLog(device_id=dev.id, status=payload.get("status", "online"), payload=payload)
    dev.status = payload.get("status", dev.status)
    db.session.add(log)
    db.session.commit()
    return jsonify({"msg": "ok"})


@bp.route("/simulate/device/<string:device_no>/command_result", methods=["POST"])
def sim_cmd_result(device_no: str):
    dev = Device.query.filter_by(device_no=device_no).first_or_404()
    data: dict[str, Any] = request.get_json(force=True)
    command_id = data.get("command_id")
    if not command_id:
        return jsonify({"msg": "missing command_id"}), 400
    cr = CommandResult(
        command_id=command_id,
        device_id=dev.id,
        success=bool(data.get("success", True)),
        message=data.get("message"),
        raw_payload=data,
    )
    rc = RemoteCommand.query.filter_by(command_id=command_id, device_id=dev.id).first()
    if rc:
        rc.status = "success" if cr.success else "failed"
    db.session.add(cr)
    db.session.commit()
    return jsonify({"msg": "ok"})
