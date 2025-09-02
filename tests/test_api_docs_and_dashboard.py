from __future__ import annotations

def test_api_docs_endpoint(client):
    rv = client.get('/api/docs')
    assert rv.status_code == 200


def test_dashboard_summary(client):
    # 登录
    from app.extensions import db
    from app.models import User, Merchant
    from app.utils.security import hash_password
    with client.application.app_context():
        m = Merchant(name="M8")
        db.session.add(m)
        db.session.flush()
        u = User(username="u8", password_hash=hash_password("p8"), role="superadmin", merchant_id=m.id)
        db.session.add(u)
        db.session.commit()
    rv = client.post('/api/auth/login', json={'username':'u8','password':'p8'})
    token = rv.get_json()['access_token']
    rv2 = client.get('/api/dashboard/summary', headers={"Authorization": f"Bearer {token}"})
    assert rv2.status_code == 200
    assert 'device_total' in rv2.get_json()
