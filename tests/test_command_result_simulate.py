from __future__ import annotations
from app.extensions import db
from app.models import User, Merchant, Device, RemoteCommand
from app.utils.security import hash_password


def prepare(client):
    with client.application.app_context():
        m = Merchant(name="M4")
        db.session.add(m)
        db.session.flush()
        u = User(username="u4", password_hash=hash_password("p4"), role="superadmin", merchant_id=m.id)
        d = Device(device_no="D400", merchant_id=m.id, status="online")
        db.session.add_all([u, d])
        db.session.commit()
    rv = client.post("/api/auth/login", json={"username": "u4", "password": "p4"})
    token = rv.get_json()["access_token"]
    return token, d  # type: ignore[name-defined]


def test_command_result_simulate(client):
    token, d = prepare(client)
    # 下发命令
    rv = client.post("/api/devices/commands", json={"device_ids":[d.id], "command_type":"reboot", "payload":{}}, headers={"Authorization": f"Bearer {token}"})
    cmd_id = rv.get_json()["command_ids"][0]
    # 模拟设备回执
    rv2 = client.post(f"/simulate/device/{d.device_no}/command_result", json={"command_id": cmd_id, "success": True})
    assert rv2.status_code == 200
