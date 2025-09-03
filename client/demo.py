#!/usr/bin/env python3
"""
咖啡机客户端演示脚本

用于演示客户端应用的各种功能，无需连接真实后端服务器
"""
import os
import sys
import time
import json
import threading
from datetime import datetime

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import Config
from app.core.hardware import SimulatedHardware
from app.core.coffee_maker import CoffeeMaker, CoffeeType

def print_header(title):
    """打印标题"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def print_status(hardware, coffee_maker):
    """打印状态信息"""
    if hasattr(hardware, 'get_status'):
        hw_status = hardware.get_status()
    else:
        hw_status = {
            'temperature': hardware.get_temperature(),
            'water_level': hardware.get_water_level(),
            'pressure': hardware.get_pressure()
        }
    
    machine_status = coffee_maker.get_machine_status()
    
    print(f"\n硬件状态:")
    print(f"  温度: {hw_status['temperature']:.1f}°C")
    print(f"  水位: {hw_status['water_level']:.1f}%")
    print(f"  压力: {hw_status['pressure']:.1f}bar")
    
    if 'components' in hw_status:
        print(f"  组件状态:")
        for component, running in hw_status['components'].items():
            status = "运行中" if running else "停止"
            print(f"    {component}: {status}")
    
    print(f"\n咖啡机状态:")
    print(f"  初始化: {'是' if machine_status['initialized'] else '否'}")
    
    if machine_status['current_job']:
        job = machine_status['current_job']
        print(f"  当前任务:")
        print(f"    类型: {job['coffee_type']}")
        print(f"    状态: {job['status']}")
        print(f"    进度: {job['progress']:.1f}%")
        if job['current_step']:
            print(f"    当前步骤: {job['current_step']}")
    else:
        print(f"  当前任务: 无")

def demo_hardware_simulation():
    """演示硬件模拟"""
    print_header("硬件模拟演示")
    
    # 创建模拟硬件
    hardware = SimulatedHardware()
    hardware.initialize()
    
    print("初始状态:")
    print_status(hardware, type('', (), {'get_machine_status': lambda: {'initialized': True, 'current_job': None}})())
    
    print("\n启动各个组件...")
    
    # 启动研磨机
    print("启动研磨机 (3秒)...")
    hardware.start_grinder(3.0)
    time.sleep(1)
    
    # 启动加热器
    print("启动加热器...")
    hardware.start_heater()
    time.sleep(1)
    
    # 启动水泵
    print("启动水泵 (5秒)...")
    hardware.start_water_pump(5.0)
    time.sleep(2)
    
    print("\n运行中状态:")
    print_status(hardware, type('', (), {'get_machine_status': lambda: {'initialized': True, 'current_job': None}})())
    
    print("\n等待组件完成...")
    time.sleep(4)
    
    print("\n最终状态:")
    print_status(hardware, type('', (), {'get_machine_status': lambda: {'initialized': True, 'current_job': None}})())
    
    hardware.cleanup()

def demo_coffee_making():
    """演示咖啡制作"""
    print_header("咖啡制作演示")
    
    # 加载配置
    config = Config()
    recipes = config.get('coffee.default_recipes', {})
    
    # 创建硬件和咖啡机
    hardware = SimulatedHardware()
    coffee_maker = CoffeeMaker(hardware, recipes)
    
    # 状态回调
    def status_callback(status_data):
        if status_data.get('event') == 'step_started':
            print(f"  → 开始步骤: {status_data.get('step')}")
        elif status_data.get('event') == 'step_completed':
            print(f"  ✓ 完成步骤: {status_data.get('step')}")
        elif status_data.get('event') == 'job_completed':
            print(f"  ★ 制作完成: 状态={status_data.get('status')}")
    
    coffee_maker.add_status_callback(status_callback)
    
    # 初始化
    if not coffee_maker.initialize():
        print("咖啡机初始化失败")
        return
    
    print("可用咖啡类型:")
    available_coffees = coffee_maker.get_available_coffees()
    for coffee_type, recipe in available_coffees.items():
        print(f"  - {recipe.get('name', coffee_type)}")
    
    # 制作意式浓缩
    print(f"\n开始制作意式浓缩...")
    job_id = coffee_maker.start_coffee('espresso')
    
    if job_id:
        print(f"任务ID: {job_id}")
        
        # 监控制作过程
        while True:
            status = coffee_maker.get_machine_status()
            
            if not status['current_job']:
                break
                
            job = status['current_job']
            if job['status'] in ['finished', 'error', 'cancelled']:
                break
            
            time.sleep(1)
        
        print("\n最终状态:")
        print_status(hardware, coffee_maker)
    else:
        print("制作启动失败")
    
    coffee_maker.cleanup()

def demo_web_interface():
    """演示Web界面"""
    print_header("Web界面演示")
    
    print("Web界面功能:")
    print("  - 主界面: 状态仪表盘和快捷操作")
    print("  - 咖啡选择: 交互式咖啡类型选择和自定义参数")
    print("  - 制作过程: 实时进度显示和状态监控")
    print("  - 设置界面: 系统配置和网络设置")
    print("  - 管理界面: 硬件测试和系统诊断")
    
    print("\n要启动Web界面，请运行:")
    print("  cd client")
    print("  python run.py")
    print("\n然后访问: http://localhost:5001")
    
    print("\nWeb界面特性:")
    print("  ✓ 响应式设计，适配触摸屏")
    print("  ✓ 实时WebSocket通信")
    print("  ✓ 现代化UI设计")
    print("  ✓ 多主题支持")
    print("  ✓ 通知系统")

def demo_api_client():
    """演示API客户端"""
    print_header("API客户端演示")
    
    from app.api.client import APIClient
    from app.config import Config
    
    config = Config()
    api_client = APIClient(config)
    
    print("API客户端功能:")
    print("  - 设备注册和认证")
    print("  - 状态上报")
    print("  - 心跳保持")
    print("  - 命令接收")
    print("  - 日志上报")
    
    print(f"\n配置的服务器地址: {config.server_url}")
    print(f"设备编号: {config.device_no}")
    
    # 测试连接（会失败，因为没有真实服务器）
    print("\n测试连接（预期会失败，因为没有后端服务器）...")
    is_healthy = api_client.is_healthy()
    print(f"连接测试结果: {'成功' if is_healthy else '失败'}")
    
    api_client.close()

def demo_configuration():
    """演示配置系统"""
    print_header("配置系统演示")
    
    config = Config()
    
    print("当前配置:")
    print(f"  设备编号: {config.device_no}")
    print(f"  服务器URL: {config.server_url}")
    print(f"  模拟模式: {'是' if config.simulation_mode else '否'}")
    print(f"  已注册: {'是' if config.is_registered else '否'}")
    
    print(f"\n硬件配置:")
    hardware_config = config.get('hardware', {})
    print(f"  模拟模式: {hardware_config.get('simulation_mode', True)}")
    if 'gpio_pins' in hardware_config:
        print(f"  GPIO引脚:")
        for component, pin in hardware_config['gpio_pins'].items():
            print(f"    {component}: GPIO {pin}")
    
    print(f"\nUI配置:")
    ui_config = config.get('ui', {})
    print(f"  主题: {ui_config.get('theme', 'dark')}")
    print(f"  语言: {ui_config.get('language', 'zh-CN')}")
    print(f"  声音: {'启用' if ui_config.get('sound_enabled', True) else '禁用'}")
    
    print(f"\n维护配置:")
    maint_config = config.get('maintenance', {})
    print(f"  自动清洗: {'启用' if maint_config.get('auto_cleaning_enabled', True) else '禁用'}")
    print(f"  清洗间隔: {maint_config.get('cleaning_interval', 7200) // 3600}小时")
    print(f"  除垢提醒: {maint_config.get('descaling_reminder', 168) // 24}天")

def main():
    """主演示函数"""
    print_header("咖啡机客户端演示")
    print("这个演示将展示咖啡机客户端应用的各个功能模块")
    print("所有演示都在模拟模式下运行，不需要实际硬件")
    
    demos = [
        ("配置系统", demo_configuration),
        ("硬件模拟", demo_hardware_simulation),
        ("咖啡制作", demo_coffee_making),
        ("API客户端", demo_api_client),
        ("Web界面", demo_web_interface)
    ]
    
    for i, (name, func) in enumerate(demos, 1):
        try:
            print(f"\n{i}. {name}")
            input("按Enter继续...")
            func()
        except KeyboardInterrupt:
            print("\n\n演示被用户中断")
            break
        except Exception as e:
            print(f"\n演示 '{name}' 出现错误: {e}")
            print("继续下一个演示...")
    
    print_header("演示结束")
    print("感谢您使用咖啡机客户端演示！")
    print("\n要运行完整的客户端应用，请执行:")
    print("  cd client")
    print("  python run.py")

if __name__ == '__main__':
    main()