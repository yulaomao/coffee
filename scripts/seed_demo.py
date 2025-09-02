"""生成演示数据（Demo）。
使用 Faker 批量生成：多商户、设备、订单、故障、工单、升级包、配方等。
示例：
  python scripts/seed_demo.py --devices 200 --orders 5000 --online-rate 0.7 --fault-rate 0.05
"""
from __future__ import annotations
import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path
import sys
from faker import Faker

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Merchant, Device, Order, Product, Fault, WorkOrder, UpgradePackage  # noqa: E402
from app.utils.helpers import file_md5  # noqa: E402


def gen_demo(devices: int, orders: int, online_rate: float, fault_rate: float, merchants: int = 5) -> None:
    fake = Faker("zh_CN")
    app = create_app()
    with app.app_context():
        # 创建商户
        ms = []
        for i in range(merchants):
            name = f"演示商户-{i+1}"
            m = Merchant.query.filter_by(name=name).first()
            if not m:
                m = Merchant(name=name)
                db.session.add(m)
                db.session.flush()
            ms.append(m)
        # 产品集
        products = []
        for pname, price in [("美式", 10.0), ("拿铁", 12.0), ("卡布奇诺", 13.0), ("摩卡", 15.0)]:
            p = Product.query.filter_by(name=pname).first()
            if not p:
                p = Product(name=pname, price=price)
                db.session.add(p)
                db.session.flush()
            products.append(p)
        # 设备
        devs = []
        for i in range(devices):
            m = ms[i % len(ms)]
            dno = f"DEMO-{1000+i}"
            d = Device.query.filter_by(device_no=dno).first()
            if not d:
                d = Device(device_no=dno, merchant_id=m.id, model=random.choice(["C1","C2","C3"]), firmware_version="1.0."+str(random.randint(0,3)))
                db.session.add(d)
                db.session.flush()
            # 在线离线
            d.status = "online" if random.random() < online_rate else "offline"
            devs.append(d)
        db.session.commit()
        # 订单（近30天）
        if orders > 0:
            batch = []
            for i in range(orders):
                d = devs[i % len(devs)]
                m_id = d.merchant_id
                p = random.choice(products)
                dt = datetime.utcnow() - timedelta(days=random.randint(0, 30), hours=random.randint(0,23), minutes=random.randint(0,59))
                o = Order(device_id=d.id, merchant_id=m_id, product_id=p.id, price=p.price, pay_method=random.choice(["wx","ali","cash"]), status=random.choice(["paid","refunded","failed","paid"]))
                o.created_at = dt
                batch.append(o)
                if len(batch) >= 1000:
                    db.session.add_all(batch)
                    db.session.commit()
                    batch.clear()
            if batch:
                db.session.add_all(batch)
                db.session.commit()
        # 故障与工单
        for d in random.sample(devs, max(1, int(len(devs) * fault_rate))):
            f = Fault(device_id=d.id, level=random.choice(["minor","major","critical"]), code="E"+str(random.randint(1,9)), message=fake.sentence())
            db.session.add(f)
            db.session.flush()
            if random.random() < 0.5:
                w = WorkOrder(device_id=d.id, fault_id=f.id, status=random.choice(["pending","in_progress","solved"]))
                db.session.add(w)
        db.session.commit()
        # 升级包占位
        for v in ["1.1.0","1.2.0"]:
            if not UpgradePackage.query.filter_by(version=v).first():
                pkg = UpgradePackage(version=v, file_name=f"demo-{v}.json", file_path=str(ROOT / "packages" / f"demo-{v}.json"), md5="demo")
                db.session.add(pkg)
        db.session.commit()
        print("Demo 数据已生成/更新")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--devices", type=int, default=200)
    parser.add_argument("--orders", type=int, default=5000)
    parser.add_argument("--online-rate", type=float, default=0.7)
    parser.add_argument("--fault-rate", type=float, default=0.05)
    args = parser.parse_args()
    gen_demo(args.devices, args.orders, args.online_rate, args.fault_rate)


if __name__ == "__main__":
    main()
