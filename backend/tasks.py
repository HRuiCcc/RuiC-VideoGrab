"""任务编排深模块：提交 URL -> 排队 -> 限并发下载 -> 状态与历史持久化。

Interface:
    submit(urls) -> list[Task]     入队新任务
    get(task_id) -> Task|None      查单个任务
    list_tasks() -> list[Task]     全部任务（新->旧）
    cancel(task_id) -> bool        取消排队中的任务

实现细节（并发上限、worker 生命周期、进度回写、JSON 持久化）全部藏在模块内。
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .engine import DownloadError, Engine
from .platforms import detect_platform

STATUS_TERMINAL = {"done", "error", "cancelled"}


@dataclass
class Task:
    id: str
    url: str
    platform: str
    status: str = "queued"  # queued|downloading|done|error|cancelled
    title: Optional[str] = None
    thumbnail: Optional[str] = None
    file: Optional[str] = None
    size: Optional[int] = None
    progress: float = 0.0
    speed: Optional[str] = None
    eta: Optional[float] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class TaskManager:
    def __init__(self, engine_factory, concurrency: int = 2,
                 persist_path: Optional[str] = None,
                 dest_root: Optional[str] = None):
        """engine_factory: Callable[[url], Engine] —— 默认 build_engine，
        测试注入假引擎；平台识别与引擎选择都藏在模块内部。"""
        self._engine_factory = engine_factory
        self._concurrency = concurrency
        self._persist_path = persist_path
        self._dest_root = dest_root
        self._sem = asyncio.Semaphore(concurrency)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._workers_started = False
        self._load_history()

    # ---------- interface ----------

    def submit(self, urls: list[str]) -> list[Task]:
        created: list[Task] = []
        for url in urls:
            task = Task(id=uuid.uuid4().hex[:8], url=url,
                        platform=detect_platform(url))
            self._tasks[task.id] = task
            self._queue.put_nowait(task.id)
            created.append(task)
        self._ensure_workers()
        self._save()
        return created

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[Task]:
        return sorted(self._tasks.values(),
                      key=lambda t: t.created_at, reverse=True)

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status != "queued":
            return False
        task.status = "cancelled"
        self._save()
        return True

    # ---------- internals ----------

    def _ensure_workers(self) -> None:
        if self._workers_started:
            return
        self._workers_started = True
        for _ in range(self._concurrency):
            asyncio.create_task(self._worker())

    async def _worker(self) -> None:
        while True:
            task_id = await self._queue.get()
            task = self._tasks.get(task_id)
            if task is None or task.status == "cancelled":
                continue
            async with self._sem:
                if task.status == "cancelled":
                    continue
                task.status = "downloading"
                self._save()
                try:
                    dest_dir = os.path.join(self._dest_root, task.id) \
                        if self._dest_root else task.id
                    engine = self._engine_factory(task.url)
                    result = await engine.download(
                        task.url,
                        dest_dir=dest_dir,
                        progress_cb=self._progress_for(task),
                    )
                    task.status = "done"
                    task.title = result.title
                    task.thumbnail = result.thumbnail
                    task.file = result.file_path
                    task.size = result.size_bytes
                    task.progress = 100.0
                    task.error = None
                except DownloadError as exc:
                    task.status = "error"
                    task.error = str(exc)
                except Exception as exc:  # 引擎意外异常也隔离到单任务
                    task.status = "error"
                    task.error = f"内部错误: {exc}"
                self._save()

    def _progress_for(self, task: Task):
        """从下载线程回调（线程安全：GIL 下属性赋值原子）。"""
        def on_progress(percent: float, speed: Optional[str],
                        eta: Optional[float]) -> None:
            task.progress = percent
            task.speed = speed
            task.eta = eta
        return on_progress

    # ---------- persistence ----------

    def _save(self) -> None:
        if not self._persist_path:
            return
        with self._lock:
            tmp = self._persist_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"tasks": [t.to_dict() for t in self._tasks.values()]},
                          fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self._persist_path)

    def _load_history(self) -> None:
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, encoding="utf-8") as fh:
                payload = json.load(fh)
            for data in payload.get("tasks", []):
                task = Task.from_dict(data)
                if task.status not in STATUS_TERMINAL:
                    task.status = "error"
                    task.error = "服务重启，任务中断"
                self._reanchor_file(task)
                self._tasks[task.id] = task
        except (json.JSONDecodeError, OSError):
            pass  # 历史损坏不影响启动

    def _reanchor_file(self, task: Task) -> None:
        """把历史 file 路径锚定到当前 dest_root（项目移动/改名后旧路径失效）。"""
        if not task.file or not self._dest_root:
            return
        root = os.path.abspath(self._dest_root)
        if os.path.abspath(task.file).startswith(root):
            return
        task.file = os.path.join(root, task.id, os.path.basename(task.file))
