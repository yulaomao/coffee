"""清除历史数据并重建数据库（谨慎使用）。

优先处理 SQLite：直接删除数据库文件（以及 -wal/-shm/-journal），
随后启动应用让其自动 create_all + 轻量升级脚本补齐列，并创建默认管理员。

非 SQLite 则回退到 drop_all + create_all。

用法：
  python scripts/reset_db.py --yes
  # 强制使用 drop_all 方式（不删文件）：
  python scripts/reset_db.py --yes --drop-all
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 确保可直接运行脚本时能找到 app 包
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.extensions import db  # noqa: E402


def _parse_sqlite_path(uri: str) -> Path | None:
    if uri.startswith("sqlite:///"):
        # "sqlite:///D:/path/to/db.sqlite" -> "D:/path/to/db.sqlite"
        p = uri.replace("sqlite:///", "", 1)
        return Path(p)
    return None


def _remove_sqlite_files(db_path: Path) -> None:
    # 删除主文件及可能存在的 -wal/-shm/-journal
    patterns = [
        db_path,
        db_path.with_suffix(db_path.suffix + "-wal"),
        db_path.with_suffix(db_path.suffix + "-shm"),
        db_path.with_suffix(db_path.suffix + "-journal"),
    ]
    for p in patterns:
        try:
            if p.exists():
                p.unlink()
        except Exception as e:
            print(f"[reset-db] 删除文件失败: {p} -> {e}")


def main() -> None:
    ap = argparse.ArgumentParser(description="危险操作：清空数据库并重建")
    ap.add_argument("--yes", action="store_true", help="跳过确认，直接执行")
    ap.add_argument(
        "--drop-all", action="store_true", help="强制使用 drop_all/create_all（不删除 SQLite 文件）"
    )
    args = ap.parse_args()

    if not args.yes:
        print("该操作将清除所有历史数据，且不可恢复。")
        ok = input("确认继续？(yes/NO): ").strip().lower() == "yes"
        if not ok:
            print("已取消。")
            return

    uri = Config.SQLALCHEMY_DATABASE_URI
    sqlite_path = _parse_sqlite_path(uri)

    if sqlite_path and not args.drop_all:
        # 直接删除 SQLite 文件
        sqlite_dir = sqlite_path.parent
        print(f"[reset-db] 移除 SQLite 文件: {sqlite_path}")
        _remove_sqlite_files(sqlite_path)
        # 确保目录依然存在
        os.makedirs(sqlite_dir, exist_ok=True)

        # 重建（create_app 会自动 create_all + ensure_sqlite_schema + 默认管理员）
        app = create_app()
        with app.app_context():
            # 触发一次连接，确保文件被创建
            db.session.execute(db.text("SELECT 1"))
        print("[reset-db] 重建完成（SQLite 文件已重建，默认管理员 admin/admin123）。")
        return

    # 非 SQLite 或者强制使用 drop_all
    print("[reset-db] 使用 drop_all/create_all 方式重建数据库……")
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
    print("[reset-db] 重建完成（已保留数据库文件路径）。")


if __name__ == "__main__":
    main()
