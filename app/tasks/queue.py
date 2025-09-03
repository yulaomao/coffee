"""内存任务队列（最小实现）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from queue import Queue
from typing import Any, Callable, Dict, Optional


@dataclass
class Task:
    id: str
    type: str
    payload: Dict[str, Any]
    status: str = "pending"  # pending/running/success/fail
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    error: Optional[str] = None


queue: "Queue[Task]" = Queue()


def submit_task(task: Task) -> None:
    queue.put(task)
