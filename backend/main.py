"""VideoGrab FastAPI 应用：薄路由层，逻辑全部在 engine/tasks 深模块里。"""
from __future__ import annotations

import mimetypes
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .engine import EngineConfig, build_engine
from .platforms import extract_urls
from .tasks import TaskManager

BASE = Path(__file__).resolve().parent.parent
DOWNLOADS = BASE / "downloads"
DATA = BASE / "data"
FRONTEND = BASE / "frontend" / "index.html"
COOKIE_FILE = DATA / "cookies.txt"
HISTORY_FILE = DATA / "history.json"

DOWNLOADS.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)

app = FastAPI(title="VideoGrab", version="0.1.0")

tm = TaskManager(
    engine_factory=lambda url: build_engine(
        url, EngineConfig(downloads_root=str(DOWNLOADS),
                          cookie_file=str(COOKIE_FILE),
                          data_dir=str(DATA))),
    concurrency=2,
    persist_path=str(HISTORY_FILE),
    dest_root=str(DOWNLOADS),
)


class SubmitBody(BaseModel):
    text: str


class CookiesBody(BaseModel):
    content: str


@app.get("/")
async def index():
    return FileResponse(FRONTEND)


@app.get("/api/health")
async def health():
    import yt_dlp
    return {"ok": True, "yt_dlp_version": yt_dlp.version.__version__}


@app.post("/api/submit")
async def submit(body: SubmitBody):
    urls = extract_urls(body.text)
    if not urls:
        raise HTTPException(status_code=400, detail="没有识别到有效链接")
    tasks = tm.submit(urls)
    return {"tasks": [t.to_dict() for t in tasks]}


@app.get("/api/tasks")
async def list_tasks():
    return {"tasks": [t.to_dict() for t in tm.list_tasks()]}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = tm.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task.to_dict()


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    return {"ok": tm.cancel(task_id)}


@app.get("/api/files/{task_id}")
async def get_file(task_id: str, dl: int = 0):
    try:
        path = resolve_task_file(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    disposition = "attachment" if dl else "inline"
    return FileResponse(path, media_type=media_type, filename=Path(path).name,
                        content_disposition_type=disposition)


def resolve_task_file(task_id: str) -> str:
    """校验任务状态与路径安全，返回可访问的文件绝对路径。"""
    task = tm.get(task_id)
    if task is None or task.status != "done" or not task.file:
        raise FileNotFoundError("文件不存在或任务未完成")
    path = Path(task.file).resolve()
    if not str(path).startswith(str(DOWNLOADS.resolve())):
        raise ValueError("非法路径")
    if not path.exists():
        raise FileNotFoundError("文件已丢失（可能已被删除）")
    return str(path)


def open_with_system_app(path: str) -> None:
    """用系统默认播放器打开文件（macOS: open / Windows: startfile / Linux: xdg-open）。"""
    if not os.path.exists(path):
        raise FileNotFoundError("文件已丢失（可能已被删除）")
    if sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    elif sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.run(["xdg-open", path], check=False)


@app.post("/api/files/{task_id}/open")
async def open_file(task_id: str):
    """在本机用系统默认播放器打开已下载文件。"""
    try:
        path = resolve_task_file(task_id)
        open_with_system_app(path)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True, "path": path}


@app.post("/api/cookies")
async def save_cookies(body: CookiesBody):
    content = body.content.strip()
    if not content:
        if COOKIE_FILE.exists():
            COOKIE_FILE.unlink()
        return {"ok": True, "configured": False}
    COOKIE_FILE.write_text(content + "\n", encoding="utf-8")
    return {"ok": True, "configured": True}


@app.get("/api/cookies")
async def cookie_status():
    return {"configured": COOKIE_FILE.exists()}
