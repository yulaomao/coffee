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
        "orders": [
            ("order_no", "order_no TEXT"),
        ],
        "remote_commands": [
            ("result_payload", "result_payload TEXT"),
            ("result_at", "result_at DATETIME"),
            ("batch_info", "batch_info TEXT"),
        ],
    }

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
