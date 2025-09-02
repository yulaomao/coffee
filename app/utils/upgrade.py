"""轻量 SQLite 架构升级：为已存在的旧表补齐新增列，避免运行期报错。

注意：仅用于 Demo/开发环境。生产环境请使用 Alembic 正式迁移。
"""
from __future__ import annotations
from typing import Dict, List
from sqlalchemy.engine import Engine


def _table_columns(engine: Engine, table: str) -> List[str]:
    cols: List[str] = []
    with engine.connect() as conn:
        res = conn.exec_driver_sql(f"PRAGMA table_info('{table}')")
        for row in res:
            # row: (cid, name, type, notnull, dflt_value, pk)
            cols.append(row[1])
    return cols


def _add_column(engine: Engine, table: str, col_def: str) -> None:
    # col_def 示例："address_detail TEXT"
    sql = f"ALTER TABLE {table} ADD COLUMN {col_def}"
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


def ensure_sqlite_schema(engine: Engine) -> None:
    """为部分关键表添加新增列（若缺失）。

    仅在 SQLite 上运行；对其它数据库不做处理。
    """
    if engine.url.get_backend_name() != "sqlite":
        return

    # 需要补齐的列定义：{table: [(name, definition), ...]}
    targets: Dict[str, List[tuple[str, str]]] = {
            "devices": [
            ("address_detail", "address_detail TEXT"),
            ("summary_address", "summary_address TEXT"),
            ("scene", "scene TEXT"),
            ("customer_code", "customer_code TEXT"),
            ("custom_fields", "custom_fields TEXT"),  # JSON 以 TEXT 存储
        ],
        "device_materials": [
            ("capacity", "capacity REAL DEFAULT 100"),
        ],
        "material_catalog": [
            ("category", "category TEXT"),
        ],
        "orders": [
            # 新增订单相关字段（尽量不加 NOT NULL 约束，避免旧表已有数据时失败）
            ("order_no", "order_no TEXT"),
            ("product_name", "product_name TEXT"),
            ("qty", "qty INTEGER DEFAULT 1"),
            ("unit_price", "unit_price NUMERIC DEFAULT 0"),
            ("total_amount", "total_amount NUMERIC DEFAULT 0"),
            ("pay_method", "pay_method TEXT DEFAULT 'cash'"),
            ("pay_status", "pay_status TEXT DEFAULT 'paid'"),
            ("status", "status TEXT DEFAULT 'paid'"),
            ("is_exception", "is_exception INTEGER DEFAULT 0"),
            ("raw_payload", "raw_payload TEXT"),
            ("refund_info", "refund_info TEXT"),
            ("created_by", "created_by INTEGER"),
        ],
        "remote_commands": [
            ("result_payload", "result_payload TEXT"),
            ("result_at", "result_at DATETIME"),
            ("batch_info", "batch_info TEXT"),
        ],
    }

    # 轻量建表（若不存在）
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS recipes (id INTEGER PRIMARY KEY, name TEXT NOT NULL, version TEXT, description TEXT, author_id INTEGER, status TEXT DEFAULT 'draft', applicable_models TEXT, bin_mapping_schema TEXT, steps TEXT, metadata TEXT, created_at TEXT, updated_at TEXT)")
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS recipe_packages (id INTEGER PRIMARY KEY, recipe_id INTEGER, package_name TEXT NOT NULL, package_path TEXT NOT NULL, md5 TEXT NOT NULL, size_bytes INTEGER NOT NULL DEFAULT 0, uploaded_by INTEGER, created_at TEXT)")
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS recipe_dispatch_batches (id TEXT PRIMARY KEY, recipe_package_id INTEGER, initiated_by INTEGER, devices TEXT NOT NULL, strategy TEXT NOT NULL, scheduled_time TEXT, status_summary TEXT, created_at TEXT)")
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS recipe_dispatch_logs (id INTEGER PRIMARY KEY, batch_id TEXT NOT NULL, device_id INTEGER NOT NULL, command_id TEXT NOT NULL, status TEXT NOT NULL, result_payload TEXT, result_at TEXT, created_at TEXT)")
    for table, defs in targets.items():
        try:
            existing = set(_table_columns(engine, table))
        except Exception:
            # 表不存在时，create_all 会负责创建；这里忽略
            continue
        for name, col_def in defs:
            if name not in existing:
                try:
                    _add_column(engine, table, col_def)
                except Exception:
                    # 尽量不阻塞应用启动；记录到控制台足矣
                    # 由于本函数不具备日志句柄，简单打印
                    print(f"[ensure_sqlite_schema] 添加列失败: {table}.{name}")
