"""初始化数据库并创建表。"""
from __future__ import annotations
from pathlib import Path
import sys

# 确保可从脚本直接运行时找到项目根目录的 app 包
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

def main() -> None:
    app = create_app()
    with app.app_context():
        db.create_all()
        print("数据库初始化完成")

if __name__ == "__main__":
    main()
