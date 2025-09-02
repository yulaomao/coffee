# 智能自售咖啡机管理系统 V6.2（最小可运行版）

本项目提供一个可直接运行的 Python Flask 后端 + 基础管理网页（Jinja2 + Bootstrap），支持：
- JWT 鉴权与 RBAC 角色（superadmin/merchant_admin/ops_engineer/viewer/finance）
- 多租户 merchant 隔离
- 设备/订单/物料/故障/工单/升级/审计日志 基础功能
- 远程命令下发与回执（支持 MQTT 可选，HTTP 回退通道必选）
- 本地文件上传（packages/）与导出（CSV）
- 后台任务（内存队列 + 线程 + APScheduler 定时任务）
- API 文档（/api/docs，Swagger UI）

该版本优先保证“最小可运行”，部分复杂功能以占位实现，后续可扩展。

## 目录结构

```
coffe/
├─ app/
│  ├─ __init__.py
│  ├─ config.py
│  ├─ extensions.py
│  ├─ models.py
│  ├─ utils/
│  │  ├─ security.py
│  │  └─ helpers.py
│  ├─ tasks/
│  │  ├─ queue.py
│  │  └─ worker.py
│  ├─ mqtt_client.py
│  ├─ blueprints/
│  │  ├─ auth.py
│  │  ├─ admin.py
│  │  ├─ devices.py
│  │  ├─ orders.py
│  │  ├─ materials.py
│  │  ├─ faults.py
│  │  ├─ upgrades.py
│  │  ├─ finance.py
│  │  ├─ operation_logs.py
│  │  ├─ recipes.py
│  │  ├─ simulate.py
│  │  └─ api_docs.py
│  ├─ templates/
│  │  ├─ base.html
│  │  ├─ login.html
│  │  ├─ dashboard.html
│  │  ├─ devices.html
│  │  ├─ device_detail.html
│  │  ├─ orders.html
│  │  ├─ upgrades.html
│  │  ├─ recipes.html
│  │  ├─ faults.html
│  │  ├─ workorders.html
│  │  ├─ finance.html
│  │  ├─ logs.html
│  │  └─ tasks.html
│  └─ static/
│     ├─ css/style.css
│     └─ js/app.js
├─ scripts/
│  ├─ init_db.py
│  └─ seed_data.py
├─ tests/
│  ├─ conftest.py
│  ├─ test_auth.py
│  ├─ test_devices.py
│  ├─ test_device_detail_and_commands.py
│  ├─ test_command_result_simulate.py
│  ├─ test_upload_package.py
│  ├─ test_workorders.py
│  └─ test_export_orders.py
├─ manage.py
├─ requirements.txt
├─ run.bat
└─ run.sh
```

## 快速开始（本地）

1) 准备环境
- Python >= 3.10
- Windows 下建议使用 PowerShell；macOS/Linux 参考 run.sh

2) 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3) 配置环境变量（也可使用默认）

- SECRET_KEY：Flask 会话密钥
- JWT_SECRET：JWT 密钥
- DATABASE_URL：默认 sqlite:///data/db.sqlite
- MQTT_BROKER_URL（可选）：配置后会尝试连接 MQTT；未配置则自动退回 HTTP 通道

PowerShell 示例：
```powershell
$env:FLASK_APP="manage.py"
$env:FLASK_ENV="development"
$env:SECRET_KEY="dev-secret"
$env:JWT_SECRET="dev-jwt-secret"
$env:DATABASE_URL="sqlite:///data/db.sqlite"
```

4) 初始化数据库并填充示例数据

```powershell
python scripts/init_db.py
python scripts/seed_data.py
# 可选：批量生成演示数据（支持大体量，默认设备200、订单5000）
python scripts/seed_demo.py --devices 200 --orders 5000 --online-rate 0.7 --fault-rate 0.05
```

5) 运行服务

```powershell
python manage.py runserver
# 或
flask run
```

浏览器访问 http://127.0.0.1:5000/ 登录页。

- 默认管理员：用户名 admin / 密码 admin123

6) 运行测试

```powershell
pytest -q

## Demo 模式与界面增强

- 顶部导航有 Demo 按钮：
  - 首次点击会通过 /api/demo/load 生成演示数据，并显示 DEMO 徽标；再次点击会调用 /api/demo/clear 清空
  - 若需要控制规模，可改为在浏览器控制台请求：
    fetch('/api/demo/load', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({devices:300, orders:8000})})
- 顶部“暗色”开关：前端本地切换浅/深色主题（localStorage 持久化），不影响服务端
- 设备列表/订单页已集成 DataTables，支持搜索/排序/分页，并提供导出 CSV 按钮
- 设备详情页：支持快速下发示例命令与模拟回执按钮
```

## 主要功能说明（最小实现）

- 登录/刷新：
  - POST /api/auth/login 返回 access_token、refresh_token
  - POST /api/auth/refresh 使用 refresh token 获取新 access token
- 仪表盘：GET /api/dashboard/summary 支持 merchant 与时间范围
- 设备：
  - GET /api/devices 支持分页/搜索（简单实现）与 CSV 导出（format=csv）
  - GET /api/devices/{id} 详情（含最近记录）
  - POST /api/devices/commands 批量下发；写入 remote_commands 并进入内存队列
  - POST /api/devices/{id}/command_result 设备回执（或用模拟接口）
- 订单：GET /api/orders 支持筛选与 CSV 导出
- 物料：GET/PUT /api/devices/{id}/materials（最小实现）
- 故障/工单：GET /api/faults，POST /api/workorders，PATCH /api/workorders/{id}
- 升级/配方：
  - POST /api/upgrades 上传包到 packages/
  - POST /api/upgrades/dispatch 下发升级
  - POST /api/recipes/package 生成 JSON 配方文件（保存在 packages/）
- 审计日志：GET /api/operation_logs，页面可检索/导出
- 模拟设备：
  - POST /simulate/device/{device_no}/status
  - POST /simulate/device/{device_no}/command_result

## 权限与多租户

- 所有 API 需 JWT；管理页面需登录（会话）
- merchant_admin 仅能查看自身商户数据；superadmin 可跨商户
- ops_engineer 可进行设备操作但无财务页面权限

## MQTT 对接

- 若设置 MQTT_BROKER_URL（如：mqtt://127.0.0.1:1883），服务会尝试连接并发布命令到 `devices/{device_no}/commands`
- 主题：
  - 设备上线/状态：devices/{device_no}/status
  - 后台下发命令：devices/{device_no}/commands
  - 命令结果：devices/{device_no}/command_result
- 若未配置或连接失败，命令会保持 pending 并由本地 worker 使用 HTTP 回退（调用设备回调 URL，示例为本服务的 /simulate 接口）

## 生产部署（可选建议）

- 使用 waitress 或 gunicorn 启动：
  - waitress：`waitress-serve --listen=0.0.0.0:8000 manage:app`
- 建议配置反向代理（Nginx）与 HTTPS

## 限制与后续扩展

- 仪表盘统计为简化聚合；可扩展为更复杂的指标与图表
- 导出/长任务使用内存队列；可替换为 Redis/RabbitMQ
- WebSocket/SSE 未默认启用，可作为加分项接入

## 数据库迁移（Alembic）

本项目已集成 Flask-Migrate（Alembic）。开发期若需稳定演进字段：

1) 初始化迁移目录（首次）
```powershell
flask db init
```
2) 生成迁移脚本
```powershell
flask db migrate -m "init"
```
3) 应用迁移
```powershell
flask db upgrade
```
注意：SQLite 对部分变更不友好，复杂变更请评估或迁移至 MySQL/PostgreSQL。

---

如遇问题，请提交 Issue 或自行扩展模块。