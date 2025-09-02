"""后台 worker：处理命令下发、导出、重试等任务（最小实现）。"""
from __future__ import annotations
import threading
import time
import uuid
from typing import Any
from flask import Flask
from ..extensions import db, scheduler
from ..models import RemoteCommand, CommandResult
from .queue import queue, Task


_worker_started = False

def start_background_worker(app: Flask) -> None:
    global _worker_started
    if _worker_started:
        return

    def _run():
        with app.app_context():
            while True:
                task: Task = queue.get()
                try:
                    task.status = "running"
                    task.updated_at = task.created_at
                    if task.type == "dispatch_command":
                        _handle_dispatch_command(task.payload)
                    elif task.type == "export_csv":
                        # 示例任务：实际应写文件到磁盘
                        time.sleep(0.2)
                    else:
                        pass
                    task.status = "success"
                except Exception as e:  # noqa: BLE001
                    task.status = "fail"
                    task.error = str(e)
                finally:
                    queue.task_done()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    _worker_started = True

    # APScheduler 示例周期任务：清理过期 pending（占位实现）
    def clean_pending():
        with app.app_context():
            # 这里只是演示任务挂钩
            pass

    scheduler.add_job(clean_pending, "interval", minutes=10, id="clean_pending")


def _handle_dispatch_command(payload: dict[str, Any]) -> None:
    """尝试下发命令：
    - 优先 MQTT（未接入则跳过）
    - 回退到 HTTP：调用本地 simulate 接口（演示）
    这里做最小实现：将命令标记为 sent。
    """
    cmd_id = payload.get("command_id")
    rc = RemoteCommand.query.filter_by(command_id=cmd_id).first()
    if not rc:
        return
    rc.status = "sent"
    db.session.commit()
