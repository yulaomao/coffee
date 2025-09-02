from __future__ import annotations
from app.extensions import db
from app.models import User, Merchant, Device
from app.utils.security import hash_password


def login_token(client):
    with client.application.app_context():
        m = Merchant(name="M2")
        db.session.add(m)
        db.session.flush()
        u = User(username="u2", password_hash=hash_password("p2"), role="superadmin", merchant_id=m.id)
        d = Device(device_no="D200", merchant_id=m.id, status="online")
        db.session.add_all([u, d])
        db.session.commit()
    rv = client.post("/api/auth/login", json={"username": "u2", "password": "p2"})
    return rv.get_json()["access_token"], d.id  # type: ignore[name-defined]


def test_list_devices(client):
    token, _ = login_token(client)
    rv = client.get("/api/devices", headers={"Authorization": f"Bearer {token}"})
    assert rv.status_code == 200
    assert "items" in rv.get_json()
