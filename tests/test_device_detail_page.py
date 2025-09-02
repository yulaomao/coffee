"""Test device detail page template behavior."""
from __future__ import annotations
from app.extensions import db
from app.models import User, Merchant, Device, Order, Product
from app.utils.security import hash_password


def prepare_data(client):
    """Prepare test data with devices and orders."""
    with client.application.app_context():
        # Create merchant with unique name using timestamp
        import time
        merchant_name = f"Test Merchant {int(time.time() * 1000)}"
        m = Merchant(name=merchant_name)
        db.session.add(m)
        db.session.flush()
        
        # Create user with unique username
        username = f"test_user_{int(time.time() * 1000)}"
        u = User(username=username, password_hash=hash_password("test_pass"), role="superadmin", merchant_id=m.id)
        
        # Create product
        p = Product(name="Test Coffee", price=15.0)
        
        # Create two devices with unique device numbers
        device_no_with = f"DEV-WITH-ORDERS-{int(time.time() * 1000)}"
        device_no_without = f"DEV-NO-ORDERS-{int(time.time() * 1000)}"
        device_with_orders = Device(device_no=device_no_with, merchant_id=m.id, status="online", model="C1", firmware_version="1.0.0")
        device_without_orders = Device(device_no=device_no_without, merchant_id=m.id, status="offline", model="C1", firmware_version="1.0.0")
        
        db.session.add_all([u, p, device_with_orders, device_without_orders])
        db.session.flush()
        
        # Create orders for the first device only
        order1 = Order(device_id=device_with_orders.id, merchant_id=m.id, product_id=p.id, price=15.0, pay_method="wx", status="paid")
        order2 = Order(device_id=device_with_orders.id, merchant_id=m.id, product_id=p.id, price=15.0, pay_method="ali", status="refunded")
        
        db.session.add_all([order1, order2])
        db.session.commit()
        
        return device_with_orders.id, device_without_orders.id, username


def test_device_detail_page_with_orders(client):
    """Test device detail page displays orders correctly."""
    device_with_orders_id, device_without_orders_id, username = prepare_data(client)
    
    # Login first
    rv = client.post("/login", data={"username": username, "password": "test_pass"}, follow_redirects=True)
    assert rv.status_code == 200
    
    # Access device detail page for device with orders
    rv = client.get(f"/devices/{device_with_orders_id}")
    assert rv.status_code == 200
    
    # Check that the page contains order data
    page_content = rv.get_data(as_text=True)
    assert "设备详情：" in page_content  # Check for device detail header
    assert "最近订单" in page_content
    assert "<table" in page_content  # Should have a table
    assert "15.0" in page_content  # Should show order prices
    assert "paid" in page_content  # Should show order status
    assert "refunded" in page_content  # Should show order status


def test_device_detail_page_without_orders(client):
    """Test device detail page displays appropriate message when no orders exist."""
    device_with_orders_id, device_without_orders_id, username = prepare_data(client)
    
    # Login first
    rv = client.post("/login", data={"username": username, "password": "test_pass"}, follow_redirects=True)
    assert rv.status_code == 200
    
    # Access device detail page for device without orders
    rv = client.get(f"/devices/{device_without_orders_id}")
    assert rv.status_code == 200
    
    # Check that the page contains appropriate messaging for no orders
    page_content = rv.get_data(as_text=True)
    assert "设备详情：" in page_content  # Check for device detail header
    assert "最近订单" in page_content
    assert "该设备暂无订单记录" in page_content  # Should show no orders message
    assert "订单数据会在设备产生交易后显示在此处" in page_content  # Should show helpful text
    # Should NOT have a table with data rows when no orders
    assert page_content.count("<table") == 0 or "alert-info" in page_content


def test_device_detail_command_functionality(client):
    """Test that command functionality still works correctly."""
    device_with_orders_id, device_without_orders_id, username = prepare_data(client)
    
    # Login first
    rv = client.post("/login", data={"username": username, "password": "test_pass"}, follow_redirects=True)
    assert rv.status_code == 200
    
    # Check that both pages contain the command section
    for device_id in [device_with_orders_id, device_without_orders_id]:
        rv = client.get(f"/devices/{device_id}")
        assert rv.status_code == 200
        
        page_content = rv.get_data(as_text=True)
        assert "下发命令（示例）" in page_content
        assert "重启" in page_content
        assert "开门" in page_content
        assert "模拟成功回执" in page_content