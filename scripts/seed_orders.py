from __future__ import annotations
"""生成示例订单数据。
用法：python -m scripts.seed_orders --days 30 --total 2000 --exception_rate 0.05 --merchant_count 3
"""
import argparse
import random
from datetime import datetime, timedelta
from faker import Faker
from app import create_app
from app.extensions import db
from app.models import Merchant, Device, Order, Product, User

fake = Faker("zh_CN")


def gen_orders(days: int, total: int, exception_rate: float, merchant_count: int):
    app = create_app()
    with app.app_context():
        # 确保至少有商户/设备/产品/用户
        merchants = Merchant.query.order_by(Merchant.id.asc()).limit(merchant_count).all()
        if not merchants:
            m = Merchant(name="示例商户")
            db.session.add(m); db.session.commit(); merchants=[m]
        devices = Device.query.all() or []
        if not devices:
            for i in range(10):
                d = Device(device_no=f"SEED-{i:04d}", merchant_id=merchants[0].id, status="online")
                db.session.add(d)
            db.session.commit()
            devices = Device.query.all()
        products = Product.query.all()
        if not products:
            for i in range(5):
                db.session.add(Product(name=fake.word(), price=random.uniform(8, 25)))
            db.session.commit(); products = Product.query.all()
        user = User.query.first()

        start = datetime.utcnow() - timedelta(days=days-1)
        for i in range(total):
            d = random.choice(devices)
            p = random.choice(products)
            qty = random.choice([1,1,1,2])
            unit = round(random.uniform(8, 25), 2)
            amount = round(unit*qty, 2)
            ts = start + timedelta(seconds=random.randint(0, days*86400))
            pm = random.choice(["wechat","alipay","cash"]) 
            status = "paid"
            is_exc = False
            refund_info = None
            if random.random() < exception_rate and pm in ("wechat","alipay"):
                # 模拟扫码异常并自动退款中
                status = "refund_pending"
                is_exc = True
                refund_info = {"auto": True, "reason": "callback_timeout"}
            o = Order(
                order_no=f"O{int(ts.timestamp())}{i:04d}",
                created_at=ts,
                device_id=d.id,
                merchant_id=d.merchant_id,
                product_id=p.id,
                product_name=p.name,
                qty=qty,
                unit_price=unit,
                total_amount=amount,
                pay_method=pm,
                pay_status=status,
                is_exception=is_exc,
                refund_info=refund_info,
                created_by=user.id if user else None,
            )
            db.session.add(o)
            if i % 500 == 0:
                db.session.flush()
        db.session.commit()
        print(f"Generated {total} orders.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--total", type=int, default=2000)
    ap.add_argument("--exception_rate", type=float, default=0.05)
    ap.add_argument("--merchant_count", type=int, default=3)
    args = ap.parse_args()
    gen_orders(args.days, args.total, args.exception_rate, args.merchant_count)
