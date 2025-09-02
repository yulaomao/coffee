from __future__ import annotations
from app.extensions import db
from app.models import User, Merchant, Device, Order
from app.utils.security import hash_password


def prepare(client):
    with client.application.app_context():
        m = Merchant(name="M7")
        db.session.add(m)
        db.session.flush()
        u = User(username="u7", password_hash=hash_password("p7"), role="superadmin", merchant_id=m.id)
        d = Device(device_no="D700", merchant_id=m.id, status="online")
        db.session.add_all([u, d])
        db.session.flush()
        db.session.add(Order(device_id=d.id, merchant_id=m.id, price=8.8, status='paid'))
        db.session.commit()
    rv = client.post("/api/auth/login", json={"username": "u7", "password": "p7"})
    token = rv.get_json()["access_token"]
    return token


def test_export_orders_csv(client):
    token = prepare(client)
    rv = client.get("/api/orders?format=csv", headers={"Authorization": f"Bearer {token}"})
    assert rv.status_code == 200
    assert rv.mimetype == "text/csv"
