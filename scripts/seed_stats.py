"""生成订单分日聚合的示例数据（可与 seed_demo 配合）。
运行：
  python scripts/seed_stats.py --days 60 --min-sales 20 --max-sales 120
效果：
  按天生成随机销量订单，若当天已有订单则会在其基础上补充至随机范围。
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta
import random
import os, sys

# 允许脚本直接运行时导入 app
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app
from app.extensions import db
from app.models import Device, Order, Product


def ensure_product():
    p = Product.query.first()
    if not p:
        p = Product(name="美式", price=12)
        db.session.add(p)
        db.session.commit()
    return p


def seed_stats(days: int, min_sales: int, max_sales: int):
    app = create_app()
    with app.app_context():
        devs = Device.query.all()
        if not devs:
            print("无设备，先运行 scripts/seed_demo.py 生成设备")
            return
        product = ensure_product()
        today = datetime.utcnow().date()
        for i in range(days):
            d = today - timedelta(days=i)
            start = datetime.combine(d, datetime.min.time())
            end = start + timedelta(days=1)
            # 当天已有销量
            current = Order.query.filter(Order.created_at >= start, Order.created_at < end).count()
            target = random.randint(min_sales, max_sales)
            to_add = max(0, target - current)
            for _ in range(to_add):
                dev = random.choice(devs)
                o = Order(device_id=dev.id, merchant_id=dev.merchant_id, product_id=product.id, price=product.price, status="paid")
                o.created_at = start + timedelta(minutes=random.randint(0, 24*60-1))
                db.session.add(o)
            if to_add:
                db.session.commit()
        print(f"已生成/补充近 {days} 天的订单聚合。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-sales", type=int, default=30)
    ap.add_argument("--max-sales", type=int, default=120)
    args = ap.parse_args()
    seed_stats(args.days, args.min_sales, args.max_sales)
