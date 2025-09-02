from __future__ import annotations
from app.extensions import db
from app.models import User, Merchant, Device
from app.utils.security import hash_password


def prepare(client):
    with client.application.app_context():
        m = Merchant(name="M3")
        db.session.add(m)
        db.session.flush()
        u = User(username="u3", password_hash=hash_password("p3"), role="superadmin", merchant_id=m.id)
        d = Device(device_no="D300", merchant_id=m.id, status="online")
        db.session.add_all([u, d])
        db.session.commit()
    rv = client.post("/api/auth/login", json={"username": "u3", "password": "p3"})
    token = rv.get_json()["access_token"]
    return token, d.id  # type: ignore[name-defined]


def test_device_detail_and_command(client):
    token, did = prepare(client)
    rv = client.get(f"/api/devices/{did}", headers={"Authorization": f"Bearer {token}"})
    assert rv.status_code == 200
    rv2 = client.post("/api/devices/commands", json={"device_ids":[did], "command_type":"reboot", "payload":{}}, headers={"Authorization": f"Bearer {token}"})
    assert rv2.status_code == 200
    assert "command_ids" in rv2.get_json()
