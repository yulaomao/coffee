# 咖啡机客户端应用

基于Python+Flask的咖啡机客户端应用，提供触摸屏友好的Web界面用于咖啡机操作和管理。

## 架构设计

### 系统架构
- **Web服务层**: Flask应用，提供HTML界面
- **控制核心**: 咖啡机核心控制逻辑
- **API客户端**: 与管理后台通信
- **WebSocket客户端**: 实时通信组件
- **硬件接口层**: 与咖啡机硬件交互（支持模拟模式）

### 通信架构
- **与后台服务器**: HTTP API + WebSocket
- **本地界面**: Flask Web界面（适合触摸屏）
- **硬件控制**: GPIO接口（或模拟接口）

## 目录结构

```
client/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── core/                    # 核心控制模块
│   │   ├── __init__.py
│   │   ├── coffee_maker.py      # 咖啡制作控制
│   │   ├── hardware.py          # 硬件接口
│   │   └── simulator.py         # 硬件模拟器
│   ├── api/                     # API通信
│   │   ├── __init__.py
│   │   ├── client.py            # 后台API客户端
│   │   └── websocket_client.py  # WebSocket客户端
│   ├── web/                     # Web界面
│   │   ├── __init__.py
│   │   ├── routes.py            # 路由
│   │   └── utils.py             # 工具函数
│   ├── static/                  # 静态资源
│   │   ├── css/
│   │   ├── js/
│   │   └── images/
│   └── templates/               # 模板文件
│       ├── base.html
│       ├── index.html           # 主界面
│       ├── coffee_select.html   # 咖啡选择
│       ├── making.html          # 制作过程
│       ├── settings.html        # 设置界面
│       └── admin.html           # 管理界面
├── config/
│   ├── default.json             # 默认配置
│   └── device.json              # 设备配置
├── logs/                        # 日志目录
├── run.py                       # 启动脚本
└── requirements.txt             # 依赖包
```

## 功能模块

### 用户界面
1. **主界面**: 状态仪表盘、咖啡选择、操作面板
2. **咖啡制作界面**: 选择参数、制作进度、结果反馈
3. **设置界面**: 网络配置、显示设置、维护向导
4. **管理员界面**: 系统诊断、网络配置、测试功能

### 核心功能
1. **咖啡制作模块**: 配方管理、制作流程控制、参数调整
2. **状态管理**: 传感器监控、状态上报、异常检测
3. **命令处理**: 命令解析、执行、结果反馈
4. **远程通信**: 认证、状态同步、指令接收

## 运行说明

1. 安装依赖: `pip install -r requirements.txt`
2. 配置设备: 编辑 `config/device.json`
3. 启动应用: `python run.py`
4. 访问界面: `http://localhost:5001`

## 模拟模式

应用支持完整的模拟模式，无需实际硬件即可演示所有功能：
- 虚拟传感器数据
- 模拟咖啡制作过程
- 故障和异常情况模拟
- 调试和测试功能