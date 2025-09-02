from __future__ import annotations
from app.extensions import db
from app.models import User, Merchant
from app.utils.security import hash_password


def test_login(client):
    with client.application.app_context():
        m = Merchant(name="T1")
        db.session.add(m)
        db.session.flush()
        u = User(username="u1", password_hash=hash_password("p1"), role="superadmin", merchant_id=m.id)
        db.session.add(u)
        db.session.commit()
    rv = client.post("/api/auth/login", json={"username": "u1", "password": "p1"})
    assert rv.status_code == 200
    assert "access_token" in rv.get_json()
