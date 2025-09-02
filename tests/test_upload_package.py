from __future__ import annotations
import io

def test_upload_package(client):
    # 登录
    from app.extensions import db
    from app.models import User, Merchant
    from app.utils.security import hash_password
    with client.application.app_context():
        m = Merchant(name="M5")
        db.session.add(m)
        db.session.flush()
        u = User(username="u5", password_hash=hash_password("p5"), role="superadmin", merchant_id=m.id)
        db.session.add(u)
        db.session.commit()
    rv = client.post("/api/auth/login", json={"username": "u5", "password": "p5"})
    token = rv.get_json()["access_token"]

    data = {
        'file': (io.BytesIO(b'content'), 'demo.json'),
        'version': 'v1'
    }
    rv2 = client.post("/api/upgrades", headers={"Authorization": f"Bearer {token}"}, data=data, content_type='multipart/form-data')
    assert rv2.status_code == 200
