"""填充示例数据。"""
from __future__ import annotations
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User, Merchant, Device, Order, Product  # noqa: E402
from app.utils.security import hash_password  # noqa: E402


def main() -> None:
    app = create_app()
    with app.app_context():
        # 商户（get-or-create）
        m1 = Merchant.query.filter_by(name="默认商户").first()
        if not m1:
            m1 = Merchant(name="默认商户")
            db.session.add(m1)
            db.session.flush()

        # 管理员（get-or-create）
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            admin = User(username="admin", password_hash=hash_password("admin123"), email="admin@example.com", role="superadmin", merchant_id=m1.id)
            db.session.add(admin)

        # 产品（get-or-create）
        latte = Product.query.filter_by(name="拿铁").first()
        if not latte:
            latte = Product(name="拿铁", price=12.0)
            db.session.add(latte)
            db.session.flush()

        # 设备（get-or-create）
        d1 = Device.query.filter_by(device_no="DEV-1001").first()
        if not d1:
            d1 = Device(device_no="DEV-1001", merchant_id=m1.id, model="C1", firmware_version="1.0.0", status="online")
            db.session.add(d1)
            db.session.flush()
        d2 = Device.query.filter_by(device_no="DEV-1002").first()
        if not d2:
            d2 = Device(device_no="DEV-1002", merchant_id=m1.id, model="C1", firmware_version="1.0.0", status="offline")
            db.session.add(d2)
            db.session.flush()

        # 订单（若 d1 无订单则添加示例）
        any_order = Order.query.filter_by(device_id=d1.id).first()
        if not any_order:
            db.session.add_all([
                Order(device_id=d1.id, merchant_id=m1.id, product_id=latte.id, price=12.0, pay_method="wx", status="paid"),
                Order(device_id=d1.id, merchant_id=m1.id, product_id=latte.id, price=12.0, pay_method="ali", status="refunded"),
            ])

        db.session.commit()
        print("示例数据已生成/更新：管理员 admin / admin123")

if __name__ == "__main__":
    main()
