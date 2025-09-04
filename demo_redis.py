#!/usr/bin/env python3
"""
测试Redis数据存储系统的完整功能演示

展示基于"设备为中心"设计的各种功能：
- 设备管理
- 订单记录
- 物料管理
- 告警处理
- 远程命令
"""
from app import create_app
from app.redis_adapters import device_adapter, order_adapter, material_adapter, alarm_adapter, command_adapter
from app.services.device_service import DeviceService, DeviceStatsService
import time
import json


def demo_redis_system():
    """Redis系统演示"""
    app = create_app()
    
    with app.app_context():
        print("=== Redis 咖啡机管理系统演示 ===\n")
        print("使用模拟Redis存储（无需真实Redis服务器）\n")
        
        # 1. 创建测试设备
        print("1. 创建测试设备...")
        device1_id = device_adapter.create({
            'device_no': 'CM001',
            'merchant_id': '1',
            'alias': '办公室咖啡机',
            'model': 'CM-2000',
            'status': 'online',
            'address': '北京市朝阳区办公大厦1层',
            'scene': '办公室',
            'location_lat': 39.9042,
            'location_lng': 116.4074
        })
        
        device2_id = device_adapter.create({
            'device_no': 'CM002', 
            'merchant_id': '1',
            'alias': '会议室咖啡机',
            'model': 'CM-3000',
            'status': 'offline',
            'address': '北京市朝阳区办公大厦3层',
            'scene': '会议室',
            'location_lat': 39.9042,
            'location_lng': 116.4074
        })
        print(f"  创建设备: {device1_id[:8]}... (CM001)")
        print(f"  创建设备: {device2_id[:8]}... (CM002)")
        
        # 2. 测试设备列表
        print("\n2. 测试设备列表功能...")
        devices_result = DeviceService.list_devices(merchant_id=1, page=1, per_page=10)
        print(f"  找到 {devices_result['total']} 台设备：")
        for device in devices_result['items']:
            print(f"    - {device['device_no']}: {device['alias']} ({device['status']})")
        
        # 3. 创建设备物料数据
        print("\n3. 设置设备物料信息...")
        # 设备1的物料 
        material_adapter.set_device_bin(device1_id, 1, {
            'material_code': 'coffee_bean_colombia',
            'remaining': 80.5,
            'capacity': 100.0,
            'threshold_low_pct': 15.0,
            'unit': 'g'
        })
        material_adapter.set_device_bin(device1_id, 2, {
            'material_code': 'milk_powder',
            'remaining': 5.2,  # 低于阈值
            'capacity': 50.0,
            'threshold_low_pct': 20.0,
            'unit': 'g'
        })
        
        bins = material_adapter.get_device_bins(device1_id)
        print(f"  设备CM001物料盒: {len(bins)} 个")
        for bin_data in bins:
            status = "正常" if float(bin_data['remaining']) > (float(bin_data['capacity']) * float(bin_data['threshold_low_pct']) / 100) else "低料"
            print(f"    盒{bin_data['bin_index']}: {bin_data['material_code']} - {bin_data['remaining']}/{bin_data['capacity']}g ({status})")
        
        low_bins = material_adapter.get_device_low_bins(device1_id)
        if low_bins:
            print(f"  低料盒: {low_bins}")
        
        # 4. 创建订单数据
        print("\n4. 创建测试订单...")
        orders_created = 0
        for i in range(5):
            order_id = f"ORD{int(time.time())}{i:02d}"
            order_adapter.create(device1_id, {
                'order_id': order_id,
                'product_name': '拿铁' if i % 2 == 0 else '美式咖啡',
                'total_price': 12.5 if i % 2 == 0 else 8.0,
                'currency': 'CNY',
                'payment_method': 'alipay',
                'payment_status': 'paid',
                'items': [{'name': '拿铁' if i % 2 == 0 else '美式咖啡', 'qty': 1}]
            })
            orders_created += 1
        
        print(f"  创建了 {orders_created} 个订单")
        
        # 获取今日统计
        today = time.strftime('%Y-%m-%d')
        daily_stats = order_adapter.get_daily_stats(device1_id, today)
        print(f"  今日统计: {daily_stats['orders_count']} 单, 营收 ¥{daily_stats['revenue']:.2f}")
        
        # 5. 创建告警
        print("\n5. 创建设备告警...")
        alarm_id = alarm_adapter.create(device1_id, {
            'type': 'material_low',
            'severity': 'warning', 
            'title': '物料不足告警',
            'description': '奶粉不足，需要及时补充',
            'status': 'open',
            'context': {'bin_index': 2, 'material_code': 'milk_powder', 'remaining': 5.2}
        })
        print(f"  创建告警: {alarm_id[:8]}...")
        
        open_alarms = alarm_adapter.get_by_device_and_status(device1_id, 'open')
        print(f"  设备开放告警: {len(open_alarms)} 个")
        for alarm in open_alarms:
            print(f"    - {alarm['title']}: {alarm['description']}")
        
        # 6. 创建远程命令
        print("\n6. 下发远程命令...")
        cmd_id = command_adapter.create(device1_id, {
            'type': 'make_product',
            'payload': {'product_name': '拿铁', 'options': {'sugar': 1, 'temperature': 'hot'}},
            'status': 'pending'
        })
        print(f"  创建命令: {cmd_id[:8]}...")
        
        # 模拟命令执行
        pending_cmd = command_adapter.get_pending_command(device1_id)
        if pending_cmd:
            print(f"  执行命令: {pending_cmd['type']}")
            command_adapter.complete_command(device1_id, pending_cmd['command_id'], 'success', {
                'execution_time': 45,
                'result': 'product_made'
            })
            print("  命令执行完成")
        
        # 7. 统计图表数据
        print("\n7. 生成图表数据...")
        series_data = DeviceStatsService.get_device_charts_data(device1_id, 'series')
        print(f"  时间序列数据: {len(series_data['dates'])} 天")
        print(f"  最近几天销量: {series_data['sales'][-3:]}")
        
        category_data = DeviceStatsService.get_device_charts_data(device1_id, 'category')
        print(f"  产品分类数据: {len(category_data['categories'])} 个产品")
        for i, category in enumerate(category_data['categories']):
            print(f"    {category}: {category_data['counts'][i]} 单")
        
        # 8. 设备状态更新
        print("\n8. 更新设备状态...")
        device_adapter.update_status(device1_id, 'maintenance', temperature=75.5, water_level=85)
        updated_device = device_adapter.get_by_id(device1_id)
        print(f"  设备状态: {updated_device['status']}")
        
        print("\n=== Redis 系统演示完成 ===")
        print("✅ 设备管理: 创建、查询、更新")
        print("✅ 物料管理: 料盒状态、低料监控")
        print("✅ 订单处理: 创建订单、日统计")
        print("✅ 告警系统: 创建告警、状态管理")
        print("✅ 远程命令: 命令队列、执行反馈")
        print("✅ 数据统计: 时间序列、分类分析")
        print("\n🎯 所有功能均基于Redis'设备为中心'的键空间设计实现")


if __name__ == "__main__":
    demo_redis_system()