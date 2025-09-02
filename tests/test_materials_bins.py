from __future__ import annotations
from app.extensions import db
from app.models import User, Merchant
from app.utils.security import hash_password


def login_token(client):
    with client.application.app_context():
        m = Merchant.query.filter_by(name="M1").first()
        if not m:
            m = Merchant(name="M1")
            db.session.add(m)
            db.session.flush()
        u = User.query.filter_by(username="u_mat").first()
        if not u:
            u = User(username="u_mat", password_hash=hash_password("p"), role="superadmin", merchant_id=m.id)
            db.session.add(u)
        db.session.commit()
    rv = client.post("/api/auth/login", json={"username": "u_mat", "password": "p"})
    assert rv.status_code == 200
    return rv.get_json()["access_token"]


def auth_hdr(token):
    return {"Authorization": f"Bearer {token}"}


def test_material_catalog_crud_and_export(client):
    tok = login_token(client)
    # create
    rv = client.post("/api/material_catalog", json={"code":"bean-A","name":"咖啡豆","unit":"g","category":"bean","default_capacity":120}, headers=auth_hdr(tok))
    assert rv.status_code == 200
    mid = rv.get_json()["data"]["id"]
    # list
    rv = client.get("/api/material_catalog?q=豆", headers=auth_hdr(tok))
    assert rv.status_code == 200
    # update
    rv = client.put(f"/api/material_catalog/{mid}", json={"description":"测试"}, headers=auth_hdr(tok))
    assert rv.status_code == 200
    # export csv
    rv = client.get("/api/material_catalog/export", headers=auth_hdr(tok))
    assert rv.status_code == 200
    assert rv.mimetype.startswith("text/csv")


def test_device_bins_flow(client):
    tok = login_token(client)
    # 创建设备
    from app.models import Device
    with client.application.app_context():
        m = Merchant.query.first()
        d = Device(device_no="TB-1001", merchant_id=m.id, status="online")
        db.session.add(d); db.session.commit(); did = d.id
    # 初始化 bins
    rv = client.post(f"/api/devices/{did}/bins", json={"bins":[{"bin_index":1,"capacity":100},{"bin_index":2,"capacity":200}]}, headers=auth_hdr(tok))
    assert rv.status_code == 200
    # 先准备物料
    client.post("/api/material_catalog", json={"code":"milk-A","name":"奶粉","unit":"g"}, headers=auth_hdr(tok))
    # 绑定 bin2 到 物料 milk-A
    rv = client.put(f"/api/devices/{did}/bins/2/bind", json={"material_code":"milk-A"}, headers=auth_hdr(tok))
    assert rv.status_code == 200
    # 导出
    rv = client.get(f"/api/devices/bins/export?device_id={did}", headers=auth_hdr(tok))
    assert rv.status_code == 200 and rv.mimetype.startswith("text/csv")


def test_device_bins_bulk_bind_json_and_csv(client):
    tok = login_token(client)
    # 设备+物料准备
    from app.models import Device
    with client.application.app_context():
        m = Merchant.query.first()
        d1 = Device(device_no="TB-2001", merchant_id=m.id)
        d2 = Device(device_no="TB-2002", merchant_id=m.id)
        db.session.add_all([d1,d2]); db.session.commit()
    client.post("/api/material_catalog", json={"code":"syrup-A","name":"糖浆","unit":"ml"}, headers=auth_hdr(tok))
    # JSON 批量
    items = [
        {"device_no":"TB-2001","bin_index":1,"material_code":"syrup-A","capacity":500},
        {"device_no":"TB-2002","bin_index":2,"material_code":"syrup-A"},
    ]
    rv = client.post("/api/devices/bins/bulk_bind", json={"items": items}, headers=auth_hdr(tok))
    assert rv.status_code == 200
    data = rv.get_json()["data"]
    assert data["ok"] >= 2
    # CSV 批量
    import io
    csv_content = "device_no,bin_index,material_code,capacity,custom_label\nTB-2001,3,syrup-A,300,糖浆3\n"
    rv = client.post("/api/devices/bins/bulk_bind_csv", data={"file": (io.BytesIO(csv_content.encode('utf-8')), 'x.csv')}, headers=auth_hdr(tok), content_type='multipart/form-data')
    assert rv.status_code == 200