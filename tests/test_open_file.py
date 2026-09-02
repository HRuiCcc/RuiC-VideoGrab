"""系统播放器打开文件 + 下载路径安全校验。不触真实 subprocess。"""
import os
import subprocess
import sys

import pytest

from backend.main import app, tm
from backend.tasks import Task

# 打开命令路由
from backend.main import open_with_system_app, resolve_task_file


def test_open_with_system_app_uses_open_on_darwin(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", fake_run)
    open_with_system_app(str(f))
    assert calls and calls[0][0] == "open"
    assert calls[0][1] == str(f)


def test_open_with_system_app_uses_startfile_on_windows(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    opened = []

    import types
    import backend.main as backend_main
    fake_os = types.SimpleNamespace(
        path=types.SimpleNamespace(exists=lambda p: True),
        startfile=lambda p: opened.append(p))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(backend_main, "os", fake_os)
    open_with_system_app(str(f))
    assert opened == [str(f)]


def test_open_with_system_app_uses_xdg_open_on_linux(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", fake_run)
    open_with_system_app(str(f))
    assert calls and calls[0][0] == "xdg-open"
    assert calls[0][1] == str(f)


def test_open_with_system_app_raises_when_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        open_with_system_app(str(tmp_path / "nope.mp4"))


def test_resolve_task_file_requires_done_task(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.main.DOWNLOADS", tmp_path)
    task = Task(id="t1", url="https://a.example/v", platform="other",
                status="done", file=str(tmp_path / "v.mp4"), title="v")
    (tmp_path / "v.mp4").write_bytes(b"x")
    tm._tasks = {"t1": task}
    path = resolve_task_file("t1")
    assert path == str(tmp_path / "v.mp4")


def test_resolve_task_file_blocks_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.main.DOWNLOADS", tmp_path)
    outside = tmp_path.parent / "evil.mp4"
    outside.write_bytes(b"x")
    task = Task(id="t2", url="https://a.example/v", platform="other",
                status="done", file=str(outside), title="evil")
    tm._tasks = {"t2": task}
    with pytest.raises(ValueError, match="非法路径"):
        resolve_task_file("t2")
    outside.unlink()


def test_resolve_task_file_404_on_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.main.DOWNLOADS", tmp_path)
    task = Task(id="t3", url="https://a.example/v", platform="other",
                status="done", file=str(tmp_path / "gone.mp4"), title="gone")
    tm._tasks = {"t3": task}
    with pytest.raises(FileNotFoundError):
        resolve_task_file("t3")
