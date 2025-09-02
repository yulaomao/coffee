"""统一示例数据脚本（适配当前版本）。

用法示例：
  python scripts/seed_data.py quick
  python scripts/seed_data.py demo --devices 200 --orders 5000 --online-rate 0.7 --fault-rate 0.05 --merchants 5
  python scripts/seed_data.py orders --days 30 --total 2000 --exception-rate 0.05 --merchant-count 3
  python scripts/seed_data.py stats --days 60 --min-sales 20 --max-sales 120
  python scripts/seed_data.py clear-demo
"""
from __future__ import annotations
import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from faker import Faker

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (  # noqa: E402
    User, Merchant, Device, Order, Product, Fault, WorkOrder, UpgradePackage, DeviceMaterial, CleaningLog, MaterialCatalog, DeviceBin
)
from app.utils.security import hash_password  # noqa: E402
from app.blueprints.recipes import Recipe  # noqa: E402
from app.blueprints.recipes import _make_recipe_package  # noqa: E402


def ensure_basics():
    """确保基础数据：默认商户、管理员、基础产品。"""
    m = Merchant.query.filter_by(name="默认商户").first()
    if not m:
        m = Merchant(name="默认商户")
        db.session.add(m)
        db.session.flush()
    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin = User(username="admin", password_hash=hash_password("admin123"), email="admin@example.com", role="superadmin", merchant_id=m.id)
        db.session.add(admin)
    # 常用产品集
    base = [("美式", 10.0), ("拿铁", 12.0), ("卡布奇诺", 13.0), ("摩卡", 15.0)]
    for name, price in base:
        p = Product.query.filter_by(name=name).first()
        if not p:
            db.session.add(Product(name=name, price=price))
    # 物料目录（示例）
    mats = [
        (1, "bean-A", "咖啡豆", "bean", "g", 120.0),
        (2, "milk-A", "奶粉", "milk", "g", 800.0),
        (3, "syrup-A", "糖浆", "syrup", "ml", 1000.0),
        (4, "cup-12oz", "纸杯", "cup", "pcs", 100.0),
        (5, "stir-rod", "搅拌棒", "accessory", "pcs", 200.0),
    ]
    for mid, code, name, cat, unit, defcap in mats:
        mc = MaterialCatalog.query.filter_by(id=mid).first()
        if not mc:
            mc = MaterialCatalog(id=mid, code=code, name=name, unit=unit, category=cat, default_capacity=defcap)
            db.session.add(mc)
    db.session.commit()
    return m


def seed_quick():
    """快速最小可用数据。"""
    m = ensure_basics()
    d1 = Device.query.filter_by(device_no="DEV-1001").first()
    if not d1:
        d1 = Device(device_no="DEV-1001", merchant_id=m.id, model="C1", firmware_version="1.0.0", status="online")
        db.session.add(d1)
        db.session.flush()
    d2 = Device.query.filter_by(device_no="DEV-1002").first()
    if not d2:
        d2 = Device(device_no="DEV-1002", merchant_id=m.id, model="C1", firmware_version="1.0.0", status="offline")
        db.session.add(d2)
        db.session.flush()
    p = Product.query.filter_by(name="拿铁").first()
    if p and not Order.query.filter_by(device_id=d1.id).first():
        now = datetime.utcnow()
        o1 = Order(order_no=f"Q{int(now.timestamp())}01", created_at=now, device_id=d1.id, merchant_id=m.id,
                   product_id=p.id, product_name=p.name, qty=1, unit_price=p.price, total_amount=p.price,
                   pay_method="cash", pay_status="paid")
        db.session.add(o1)
    db.session.commit()
    print("[quick] 管理员 admin/admin123，设备 DEV-1001/DEV-1002，示例订单 1 条。")
    # 初始化设备料盒（新架构）
    for d in (d1, d2):
        if DeviceBin.query.filter_by(device_id=d.id).count() == 0:
            # 简单三格：1-咖啡豆，2-奶粉，3-糖浆
            db.session.add(DeviceBin(device_id=d.id, bin_index=1, material_id=1, capacity=120.0, unit='g', custom_label='咖啡豆'))
            db.session.add(DeviceBin(device_id=d.id, bin_index=2, material_id=2, capacity=800.0, unit='g', custom_label='奶粉'))
            db.session.add(DeviceBin(device_id=d.id, bin_index=3, material_id=3, capacity=1000.0, unit='ml', custom_label='糖浆'))
    db.session.commit()


def seed_demo(devices: int, orders: int, online_rate: float, fault_rate: float, merchants: int):
    """大规模 Demo 数据。"""
    fake = Faker("zh_CN")
    ensure_basics()
    ms = []
    for i in range(merchants):
        name = f"演示商户-{i+1}"
        m = Merchant.query.filter_by(name=name).first()
        if not m:
            m = Merchant(name=name)
            db.session.add(m)
            db.session.flush()
        ms.append(m)
    products = Product.query.all()
    devs = []
    for i in range(devices):
        m = ms[i % len(ms)]
        dno = f"DEMO-{1000+i}"
        d = Device.query.filter_by(device_no=dno).first()
        if not d:
            d = Device(device_no=dno, merchant_id=m.id, model=random.choice(["C1","C2","C3"]), firmware_version="1.0."+str(random.randint(0,3)))
            db.session.add(d)
            db.session.flush()
        d.status = "online" if random.random() < online_rate else "offline"
        devs.append(d)
    db.session.commit()

    # 旧物料（为每台设备造 3-4 个料盒，兼容旧页面）
    for d in devs:
        exist = DeviceMaterial.query.filter_by(device_id=d.id).count()
        if not exist:
            for mid in range(1, 5):
                db.session.add(DeviceMaterial(device_id=d.id, material_id=mid, remain=random.uniform(10, 100), capacity=100, threshold=10))
    db.session.commit()

    # 新料盒（DeviceBin）初始化（每台 3 格）
    for d in devs:
        if DeviceBin.query.filter_by(device_id=d.id).count() == 0:
            db.session.add(DeviceBin(device_id=d.id, bin_index=1, material_id=1, capacity=120.0, unit='g'))
            db.session.add(DeviceBin(device_id=d.id, bin_index=2, material_id=2, capacity=800.0, unit='g'))
            db.session.add(DeviceBin(device_id=d.id, bin_index=3, material_id=3, capacity=1000.0, unit='ml'))
    db.session.commit()

    # 订单
    if orders > 0 and products:
        batch = []
        for i in range(orders):
            d = devs[i % len(devs)]
            p = random.choice(products)
            qty = random.choice([1,1,2])
            unit = round(float(p.price), 2)
            amount = round(unit*qty, 2)
            dt = datetime.utcnow() - timedelta(days=random.randint(0, 30), hours=random.randint(0,23), minutes=random.randint(0,59))
            pm = random.choice(["wechat","alipay","cash"])
            status = random.choice(["paid","paid","refunded","failed"])  # 倾向于已支付
            o = Order(order_no=f"D{int(dt.timestamp())}{i:05d}", created_at=dt, device_id=d.id, merchant_id=d.merchant_id,
                      product_id=p.id, product_name=p.name, qty=qty, unit_price=unit, total_amount=amount,
                      pay_method=pm, pay_status=status, is_exception=(status!="paid" and pm!="cash"))
            batch.append(o)
            if len(batch) >= 1000:
                db.session.add_all(batch); db.session.commit(); batch.clear()
        if batch:
            db.session.add_all(batch); db.session.commit()

    # 故障/工单（按比例）
    for d in random.sample(devs, max(1, int(len(devs) * fault_rate)) or 1):
        f = Fault(device_id=d.id, level=random.choice(["minor","major","critical"]), code=f"E{random.randint(1,9)}", message=fake.sentence())
        db.session.add(f); db.session.flush()
        if random.random() < 0.5:
            db.session.add(WorkOrder(device_id=d.id, fault_id=f.id, status=random.choice(["pending","in_progress","solved"])) )
    db.session.commit()

    # 清洗日志（每台设备近 10 条）
    now = datetime.utcnow()
    for d in devs:
        if CleaningLog.query.filter_by(device_id=d.id).count() == 0:
            for k in range(10):
                dt = now - timedelta(days=random.randint(0, 30), hours=random.randint(0,23))
                db.session.add(CleaningLog(device_id=d.id, type=random.choice(["rinse","deep","steam"]), result=random.choice(["success","success","fail"]), duration_ms=random.randint(10000, 120000), note=None, created_at=dt))
    db.session.commit()

    # 升级包占位
    for v in ["1.1.0","1.2.0"]:
        if not UpgradePackage.query.filter_by(version=v).first():
            db.session.add(UpgradePackage(version=v, file_name=f"demo-{v}.json", file_path=str(ROOT / "packages" / f"demo-{v}.json"), md5="demo"))
    db.session.commit()
    print(f"[demo] 商户{merchants}、设备{devices}、订单{orders} 已生成/更新。")


def seed_orders(days: int, total: int, exception_rate: float, merchant_count: int):
    """按总量生成更真实的订单集（包含扫码异常 -> 退款中的场景）。"""
    ensure_basics()
    merchants = Merchant.query.order_by(Merchant.id.asc()).limit(merchant_count).all()
    if not merchants:
        merchants = [ensure_basics()]
    devices = Device.query.all()
    if not devices:
        # 至少造几台设备
        for i in range(10):
            db.session.add(Device(device_no=f"SEED-{i:04d}", merchant_id=merchants[0].id, status="online"))
        db.session.commit(); devices = Device.query.all()
    products = Product.query.all()
    if not products:
        ensure_basics(); products = Product.query.all()
    user = User.query.first()

    start = datetime.utcnow() - timedelta(days=days-1)
    for i in range(total):
        d = random.choice(devices)
        p = random.choice(products)
        qty = random.choice([1,1,1,2])
        unit = round(float(p.price), 2)
        amount = round(unit*qty, 2)
        ts = start + timedelta(seconds=random.randint(0, days*86400))
        pm = random.choice(["wechat","alipay","cash"])
        status = "paid"
        is_exc = False
        refund_info = None
        if random.random() < exception_rate and pm in ("wechat","alipay"):
            status = "refund_pending"  # 主动发起退款中
            is_exc = True
            refund_info = {"auto": True, "reason": "callback_timeout"}
        o = Order(order_no=f"O{int(ts.timestamp())}{i:06d}", created_at=ts, device_id=d.id, merchant_id=d.merchant_id,
                  product_id=p.id, product_name=p.name, qty=qty, unit_price=unit, total_amount=amount,
                  pay_method=pm, pay_status=status, is_exception=is_exc, refund_info=refund_info,
                  created_by=user.id if user else None)
        db.session.add(o)
        if i % 500 == 0:
            db.session.flush()
    db.session.commit()
    print(f"[orders] 生成订单 {total} 条。")


def seed_stats(days: int, min_sales: int, max_sales: int):
    """按天补齐销量范围。"""
    ensure_basics()
    devs = Device.query.all()
    if not devs:
        print("[stats] 无设备，请先生成 demo 或 orders。")
        return
    p = Product.query.first()
    today = datetime.utcnow().date()
    for i in range(days):
        d = today - timedelta(days=i)
        start = datetime.combine(d, datetime.min.time())
        end = start + timedelta(days=1)
        current = Order.query.filter(Order.created_at >= start, Order.created_at < end).count()
        target = random.randint(min_sales, max_sales)
        to_add = max(0, target - current)
        for _ in range(to_add):
            dev = random.choice(devs)
            qty = 1
            unit = round(float(p.price), 2)
            amount = unit*qty
            o = Order(order_no=f"S{int(start.timestamp())}{random.randint(0,999999):06d}", created_at=start + timedelta(minutes=random.randint(0, 24*60-1)),
                      device_id=dev.id, merchant_id=dev.merchant_id, product_id=p.id, product_name=p.name,
                      qty=qty, unit_price=unit, total_amount=amount, pay_method="cash", pay_status="paid")
            db.session.add(o)
        if to_add:
            db.session.commit()
    print(f"[stats] 已补齐近 {days} 天销量范围。")


def clear_demo():
    """清空 Demo 设备相关的订单/故障/工单等（保留管理员和默认商户）。"""
    # 先删除关联订单
    dev_ids = [d.id for d in Device.query.filter(Device.device_no.like("DEMO-%")).all()]
    if dev_ids:
        Order.query.filter(Order.device_id.in_(dev_ids)).delete(synchronize_session=False)
        WorkOrder.query.filter(WorkOrder.device_id.in_(dev_ids)).delete(synchronize_session=False)
        Fault.query.filter(Fault.device_id.in_(dev_ids)).delete(synchronize_session=False)
    Device.query.filter(Device.device_no.like("DEMO-%")).delete(synchronize_session=False)
    db.session.commit()
    print("[clear-demo] 已清空 DEMO-* 相关数据。")


def seed_recipes(with_packages: bool = True):
    """创建示例配方，并可选生成配方包。"""
    samples = [
        {
            "name": "Espresso",
            "version": "v1.0.0",
            "description": "经典意式浓缩",
            "steps": [
                {"step_id":"s1","type":"grind","params":{"dose_g":18,"grind_time_ms":6000,"grind_level":5}},
                {"step_id":"s2","type":"tamp","params":{"pressure_kpa":30,"duration_ms":1500}},
                {"step_id":"s3","type":"brew","params":{"water_ml":40,"water_temp_c":92,"pump_time_ms":25000}},
            ],
            "bin_mapping_schema": {"bin1":"coffee_beans_A"},
            "applicable_models": ["C1-1.0+"],
        },
        {
            "name": "Latte",
            "version": "v1.0.0",
            "description": "拿铁",
            "steps": [
                {"step_id":"s1","type":"grind","params":{"dose_g":18,"grind_time_ms":6200,"grind_level":5}},
                {"step_id":"s2","type":"tamp","params":{"pressure_kpa":30,"duration_ms":1500}},
                {"step_id":"s3","type":"brew","params":{"water_ml":35,"water_temp_c":92,"pump_time_ms":23000}},
                {"step_id":"s4","type":"milk","params":{"milk_ml":180,"steam_time_ms":12000}},
            ],
            "bin_mapping_schema": {"bin1":"coffee_beans_A","bin2":"milk_A"},
            "applicable_models": ["C1-1.0+","C2-2.0+"],
        },
    ]
    created = 0
    pkgs = 0
    for s in samples:
        exists = Recipe.query.filter_by(name=s["name"], version=s["version"]).first()
        if exists:
            continue
        r = Recipe(name=s["name"], version=s["version"], description=s["description"],
                   steps=s["steps"], bin_mapping_schema=s["bin_mapping_schema"],
                   applicable_models=s["applicable_models"], status="published")
        db.session.add(r)
        db.session.commit()
        created += 1
        if with_packages:
            _make_recipe_package(r, uploader_id=None)
            pkgs += 1
    print(f"[recipes] 新建 {created} 个配方，生成包 {pkgs} 个（已存在的跳过）。")


def main():
    ap = argparse.ArgumentParser(description="统一示例数据脚本")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("quick", help="快速最小数据")

    p_demo = sub.add_parser("demo", help="大规模演示数据")
    p_demo.add_argument("--devices", type=int, default=200)
    p_demo.add_argument("--orders", type=int, default=5000)
    p_demo.add_argument("--online-rate", type=float, default=0.7)
    p_demo.add_argument("--fault-rate", type=float, default=0.05)
    p_demo.add_argument("--merchants", type=int, default=5)

    p_ord = sub.add_parser("orders", help="生成真实感订单集")
    p_ord.add_argument("--days", type=int, default=30)
    p_ord.add_argument("--total", type=int, default=2000)
    p_ord.add_argument("--exception-rate", type=float, default=0.05)
    p_ord.add_argument("--merchant-count", type=int, default=3)

    p_stats = sub.add_parser("stats", help="按天补齐销量范围")
    p_stats.add_argument("--days", type=int, default=60)
    p_stats.add_argument("--min-sales", type=int, default=20)
    p_stats.add_argument("--max-sales", type=int, default=120)

    sub.add_parser("clear-demo", help="清空 DEMO-* 数据")

    p_rec = sub.add_parser("recipes", help="创建示例配方")
    p_rec.add_argument("--no-packages", action="store_true", help="仅建配方，不生成包")

    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        if args.cmd == "quick":
            seed_quick()
        elif args.cmd == "demo":
            seed_demo(args.devices, args.orders, args.online_rate, args.fault_rate, args.merchants)
        elif args.cmd == "orders":
            seed_orders(args.days, args.total, args.exception_rate, args.merchant_count)
        elif args.cmd == "stats":
            seed_stats(args.days, args.min_sales, args.max_sales)
        elif args.cmd == "clear-demo":
            clear_demo()
        elif args.cmd == "recipes":
            seed_recipes(with_packages=not args.no_packages)


if __name__ == "__main__":
    main()
