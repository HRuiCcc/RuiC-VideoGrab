"""切片2：TaskManager 队列/并发/状态流转。引擎以假对象注入，不触网。"""
import asyncio

import pytest

from backend.engine import DownloadError, DownloadResult
from backend.tasks import TaskManager

GATE = "gate"
BLOCK = "block"


class FakeEngine:
    """可编程假引擎：gate 事件控制下载阻塞，errors 指定哪些 URL 报错。"""

    def __init__(self, gate: asyncio.Event | None = None, errors: set[str] | None = None,
                 on_progress: bool = False):
        self.gate = gate
        self.errors = errors or set()
        self.started: list[str] = []
        self.on_progress = on_progress

    async def download(self, url, dest_dir, progress_cb):
        self.started.append(url)
        if self.on_progress:
            # 进度在阻塞下载期间推进，先于 gate 释放，模拟真实下载行为
            progress_cb(50.0, "1.5MiB/s", 3)
        if self.gate is not None:
            await self.gate.wait()
        if url in self.errors:
            raise DownloadError(f"下载失败: {url}")
        if self.on_progress:
            progress_cb(100.0, None, None)
        return DownloadResult(title=f"标题-{url}", thumbnail=None,
                              file_path=f"{dest_dir}/{url}.mp4", size_bytes=1024)


async def wait_until(cond, timeout=2.0):
    """轮询等待条件成立，超时抛异常带诊断信息。"""
    async def _poll():
        while not cond():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(_poll(), timeout)


def test_submit_creates_queued_tasks():
    gate = asyncio.Event()

    async def scenario():
        tm = TaskManager(lambda url: FakeEngine(gate=gate), concurrency=2)
        tasks = tm.submit(["https://a.example/1"])
        assert tasks[0].status == "queued"
        gate.set()
        await wait_until(lambda: tm.get(tasks[0].id).status == "done")

    asyncio.run(scenario())


def test_concurrency_is_limited_to_two():
    gate = asyncio.Event()

    async def scenario():
        tm = TaskManager(lambda url: FakeEngine(gate=gate), concurrency=2)
        tasks = tm.submit([f"https://a.example/{i}" for i in range(3)])
        await wait_until(lambda: len([t for t in tm.list_tasks()
                                      if t.status == "downloading"]) == 2)
        statuses = sorted(t.status for t in tm.list_tasks())
        assert statuses == ["downloading", "downloading", "queued"]
        gate.set()
        await wait_until(lambda: all(t.status == "done" for t in tm.list_tasks()))

    asyncio.run(scenario())


def test_failure_is_recorded_and_other_tasks_continue():
    async def scenario():
        tm = TaskManager(lambda url: FakeEngine(errors={"https://a.example/1"}),
                         concurrency=2)
        tm.submit([f"https://a.example/{i}" for i in range(3)])
        await wait_until(lambda: all(t.status in ("done", "error")
                                     for t in tm.list_tasks()))
        by_url = {t.url: t for t in tm.list_tasks()}
        assert by_url["https://a.example/0"].status == "done"
        assert by_url["https://a.example/1"].status == "error"
        assert "下载失败" in by_url["https://a.example/1"].error
        assert by_url["https://a.example/2"].status == "done"

    asyncio.run(scenario())


def test_success_records_title_file_and_size():
    async def scenario():
        tm = TaskManager(lambda url: FakeEngine(), concurrency=1)
        [task] = tm.submit(["https://a.example/v"])
        await wait_until(lambda: tm.get(task.id).status == "done")
        done = tm.get(task.id)
        assert done.title == "标题-https://a.example/v"
        assert done.file is not None and done.file.endswith(".mp4")
        assert done.size == 1024
        assert done.error is None

    asyncio.run(scenario())


def test_cancel_queued_task_never_downloads():
    gate = asyncio.Event()

    async def scenario():
        engine = FakeEngine(gate=gate)
        tm = TaskManager(lambda url: engine, concurrency=1)
        [first, second] = tm.submit(["https://a.example/1", "https://a.example/2"])
        await wait_until(lambda: "https://a.example/1" in engine.started)
        assert tm.cancel(second.id) is True
        gate.set()
        await wait_until(lambda: tm.get(first.id).status == "done")
        await asyncio.sleep(0.05)  # 给被取消任务一个「若被错误执行」的机会窗口
        assert tm.get(second.id).status == "cancelled"
        assert "https://a.example/2" not in engine.started

    asyncio.run(scenario())


def test_cancel_unknown_task_returns_false():
    async def scenario():
        tm = TaskManager(lambda url: FakeEngine(), concurrency=1)
        assert tm.cancel("nope") is False

    asyncio.run(scenario())


def test_progress_callback_updates_task_state():
    gate = asyncio.Event()

    async def scenario():
        tm = TaskManager(lambda url: FakeEngine(gate=gate, on_progress=True),
                         concurrency=1)
        [task] = tm.submit(["https://a.example/p"])
        await wait_until(lambda: tm.get(task.id).status == "downloading")
        await wait_until(lambda: tm.get(task.id).progress == 50.0)
        mid = tm.get(task.id)
        assert mid.speed == "1.5MiB/s"
        assert mid.eta == 3
        gate.set()
        await wait_until(lambda: tm.get(task.id).status == "done")
        assert tm.get(task.id).progress == 100.0

    asyncio.run(scenario())


def test_history_is_persisted_and_reloaded(tmp_path):
    path = tmp_path / "history.json"

    async def scenario():
        tm = TaskManager(lambda url: FakeEngine(), concurrency=1,
                         persist_path=str(path))
        [task] = tm.submit(["https://a.example/saved"])
        await wait_until(lambda: tm.get(task.id).status == "done")
        tm2 = TaskManager(lambda url: FakeEngine(), concurrency=1,
                          persist_path=str(path))
        assert tm2.get(task.id) is not None
        assert tm2.get(task.id).title == "标题-https://a.example/saved"

    asyncio.run(scenario())


def test_history_file_path_is_reanchored_after_project_move(tmp_path):
    """项目改名/移动后，旧绝对路径重新锚定到当前 dest_root。"""
    from backend.tasks import Task

    async def scenario():
        tm = TaskManager(lambda url: FakeEngine(), concurrency=1,
                         dest_root=str(tmp_path / "dl"))
        task = Task(id="abc123", url="https://a.example/v", platform="other",
                    status="done", title="旧任务",
                    file="/old/location/dl/abc123/video.mp4")
        tm._tasks[task.id] = task
        tm._reanchor_file(task)
        assert task.file == str(tmp_path / "dl" / "abc123" / "video.mp4")

    asyncio.run(scenario())
