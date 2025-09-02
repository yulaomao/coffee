from __future__ import annotations
from app.extensions import db
from app.models import User, Merchant, Device
from app.utils.security import hash_password


def prepare(client):
    with client.application.app_context():
        m = Merchant(name="M6")
        db.session.add(m)
        db.session.flush()
        u = User(username="u6", password_hash=hash_password("p6"), role="superadmin", merchant_id=m.id)
        d = Device(device_no="D600", merchant_id=m.id, status="online")
        db.session.add_all([u, d])
        db.session.commit()
    rv = client.post("/api/auth/login", json={"username": "u6", "password": "p6"})
    token = rv.get_json()["access_token"]
    return token, d.id  # type: ignore[name-defined]


def test_create_workorder(client):
    token, did = prepare(client)
    rv = client.post("/api/workorders", json={"device_id": did, "note": "fix"}, headers={"Authorization": f"Bearer {token}"})
    assert rv.status_code == 200
