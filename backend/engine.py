"""下载引擎深接口：调用方只需要知道一个 download 方法。

Interface:
    async download(url, dest_dir, progress_cb) -> DownloadResult
    - progress_cb(percent: float|None, speed: str|None, eta: float|None)
    - 失败抛 DownloadError（携带可展示给用户的中文原因）

实现侧适配器：
    YtDlpEngine —— yt-dlp 通用引擎，覆盖 1000+ 站点
    XhsEngine   —— 小红书专用（直连笔记页 JSON，视频/图集，可选登录 cookie）
路由在 build_engine。
"""
from __future__ import annotations

import asyncio
import http.cookiejar
import json
import os
import re
import time
import zipfile
from dataclasses import dataclass
from typing import Callable, Optional

import httpx
import yt_dlp


class DownloadError(Exception):
    """下载失败，message 为可直接展示给用户的中文原因。"""


@dataclass
class DownloadResult:
    title: str
    thumbnail: Optional[str]
    file_path: str
    size_bytes: Optional[int]


ProgressCallback = Callable[[Optional[float], Optional[str], Optional[float]], None]

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _clean_filename(name: str, limit: int = 80) -> str:
    name = _ANSI_RE.sub("", name)
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name).strip(" ._")
    return name[:limit] or "video"


def _strip_ansi(text: Optional[str]) -> Optional[str]:
    return _ANSI_RE.sub("", text) if text else None


@dataclass
class EngineConfig:
    downloads_root: str = "downloads"
    cookie_file: Optional[str] = None  # 用户登录 cookies（Netscape），存在才启用
    data_dir: str = "data"             # 自举缓存目录（如 B站 buvid）


class Engine:
    """抽象深接口：适配器必须实现的唯一方法。"""

    async def download(self, url: str, dest_dir: str,
                       progress_cb: ProgressCallback) -> DownloadResult:
        raise NotImplementedError


# ---------------------------------------------------------------- YtDlpEngine

class YtDlpEngine(Engine):
    """通用适配器：覆盖 yt-dlp 支持的 1000+ 站点（YouTube/B站/抖音/TikTok/Ins/X/微博…）。"""

    def __init__(self, config: EngineConfig):
        self.config = config

    async def download(self, url: str, dest_dir: str,
                       progress_cb: ProgressCallback) -> DownloadResult:
        return await asyncio.to_thread(self._download_sync, url, dest_dir, progress_cb)

    def _download_sync(self, url: str, dest_dir: str,
                       progress_cb: ProgressCallback) -> DownloadResult:
        os.makedirs(dest_dir, exist_ok=True)
        finished: list[str] = []

        def hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                pct = d.get("downloaded_bytes", 0) / total * 100 if total else None
                progress_cb(pct, _strip_ansi(d.get("_speed_str")), d.get("eta"))
            elif d.get("status") == "finished":
                path = d.get("filename") or d.get("filepath")
                if path:
                    finished.append(path)

        opts = {
            "outtmpl": os.path.join(dest_dir, "%(title).150B [%(id)s].%(ext)s"),
            "noplaylist": True,
            "merge_output_format": "mp4",
            "progress_hooks": [hook],
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            # YouTube JS 挑战需要远端求解组件（deno），从 GitHub 拉取
            "remote_components": ["ejs:github"],
        }
        cookie_file = self._cookie_file_for(url)
        if cookie_file:
            opts["cookiefile"] = cookie_file
        url = self._resolve_short_link(url)

        info: dict = {}
        for attempt in range(3):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True) or {}
                break
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.PostProcessingError,
                    FileNotFoundError) as exc:
                # 已知竞态：ffmpeg 合并成功但 yt-dlp 清理中间文件后仍访问它报错。
                # 成品已存在即视为成功，仅补拉元数据。
                if self._find_media(dest_dir):
                    info = self._extract_meta_only(url)
                    break
                # B站 412 风控间歇发作：刷新自举 cookie 重试
                if attempt < 2 and self._is_risk_control(str(exc)):
                    self._refresh_bootstrap()
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise DownloadError(self._friendly_error(str(exc))) from exc

        path = self._pick_final_path(dest_dir, finished)
        if not path:
            raise DownloadError("下载完成但未找到产出文件（可能只有直播流/不可下载内容）")

        return DownloadResult(
            title=info.get("title") or os.path.basename(path),
            thumbnail=info.get("thumbnail"),
            file_path=path,
            size_bytes=os.path.getsize(path),
        )

    def _refresh_bootstrap(self) -> None:
        from .bilibili import ensure_bootstrap
        try:
            ensure_bootstrap(self.config.data_dir, max_age_seconds=0)
        except Exception:
            pass

    @staticmethod
    def _is_risk_control(msg: str) -> bool:
        lowered = msg.lower()
        return "412" in msg or "precondition failed" in lowered

    @staticmethod
    def _is_intermediate(name: str) -> bool:
        return bool(re.search(r"\.f\d+\.[a-z0-9]{2,5}$", name)) or \
            name.endswith((".part", ".ytdl", ".temp"))

    @classmethod
    def _pick_final_path(cls, dest_dir: str, finished: list[str]) -> Optional[str]:
        """从引擎记录的 finished 文件里挑真正存在的成品，跳过已删除的中转分片。"""
        for path in reversed(finished):
            if os.path.exists(path) and not cls._is_intermediate(path):
                return path
        return cls._find_media(dest_dir)

    @staticmethod
    def _extract_meta_only(url: str) -> dict:
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                   "skip_download": True, "noplaylist": True}) as ydl:
                return ydl.extract_info(url, download=False) or {}
        except Exception:
            return {}

    def _cookie_file_for(self, url: str) -> Optional[str]:
        """用户登录 cookie 优先；B站无登录时用 buvid 自举绕过 412 风控。"""
        if self.config.cookie_file and os.path.exists(self.config.cookie_file):
            return self.config.cookie_file
        from .platforms import detect_platform
        if detect_platform(url) == "bilibili":
            from .bilibili import ensure_bootstrap
            return ensure_bootstrap(self.config.data_dir)
        return None

    @staticmethod
    def _resolve_short_link(url: str) -> str:
        """b23.tv 短链解析为 bilibili.com 规范链接，避免落到 generic 提取器被风控。"""
        if "b23.tv" not in url:
            return url
        try:
            resp = httpx.get(url, headers={"User-Agent": _XHS_HEADERS["User-Agent"]},
                             follow_redirects=True, timeout=15)
            final = str(resp.url)
            if "bilibili.com" in final:
                return final
        except Exception:
            pass
        return url

    @classmethod
    def _find_media(cls, dest_dir: str) -> Optional[str]:
        exts = (".mp4", ".mkv", ".webm", ".mov", ".flv", ".m4a", ".mp3",
                ".jpg", ".jpeg", ".png", ".webp", ".gif", ".zip")
        candidates = [os.path.join(dest_dir, f) for f in os.listdir(dest_dir)
                      if f.lower().endswith(exts)
                      and not cls._is_intermediate(f)]
        return max(candidates, key=os.path.getmtime) if candidates else None

    @staticmethod
    def _friendly_error(raw: str) -> str:
        msg = _strip_ansi(raw) or raw
        msg = msg.splitlines()[0] if msg.splitlines() else msg
        msg = msg.strip()
        lowered = msg.lower()
        if "private video" in lowered:
            return "视频是私密的，无法下载"
        if "sign in to confirm" in lowered or "confirm your age" in lowered:
            return "需要登录才能下载：请到「设置」配置 cookies 后重试"
        if "unavailable" in lowered or "not available" in lowered:
            return "视频不可用（可能已删除或地区受限）"
        if "requested format" in lowered:
            return "暂无可用画质/格式"
        if "copyright" in lowered:
            return "内容受版权保护，无法下载"
        return f"下载失败：{msg[:200]}"


# ----------------------------------------------------------------- XhsEngine

_XHS_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Referer": "https://www.xiaohongshu.com/",
}


class XhsEngine(Engine):
    """小红书专用适配器：直连笔记页 JSON，视频/图集均支持，可选登录 cookie。

    无 cookie 时尽力而为；被要求登录（461）时给出清晰指引。
    """

    def __init__(self, config: EngineConfig):
        self.config = config

    async def download(self, url: str, dest_dir: str,
                       progress_cb: ProgressCallback) -> DownloadResult:
        return await asyncio.to_thread(self._download_sync, url, dest_dir, progress_cb)

    def _client(self) -> httpx.Client:
        jar = http.cookiejar.MozillaCookieJar()
        if self.config.cookie_file and os.path.exists(self.config.cookie_file):
            try:
                jar.load(self.config.cookie_file, ignore_discard=True, ignore_expires=True)
            except Exception:
                pass
        return httpx.Client(headers=_XHS_HEADERS, cookies=jar,
                            follow_redirects=True, timeout=30)

    def _download_sync(self, url: str, dest_dir: str,
                       progress_cb: ProgressCallback) -> DownloadResult:
        os.makedirs(dest_dir, exist_ok=True)
        with self._client() as client:
            page_url = self._resolve_page_url(client, url)
            note_id = self._note_id_from_url(page_url)
            if not note_id:
                raise DownloadError("无法解析小红书笔记 ID，请检查链接是否完整")
            page = client.get(page_url)
            if page.status_code in (461, 418) or "登录后查看" in page.text:
                raise DownloadError(
                    "小红书需要登录 cookie：请到「设置」粘贴 cookies.txt 后重试")
            note = self._find_note(page.text, note_id)
            if note is None:
                raise DownloadError("未找到笔记内容：可能已删除、仅粉丝可见，或需要登录 cookie")

            title = _clean_filename(note.get("title") or
                                    f"{note.get('user', {}).get('nickname', '笔记')}_{note_id}")
            thumb = self._cover(note)
            if note.get("type") == "video":
                path = self._download_video(client, note, dest_dir, title, progress_cb)
            else:
                path = self._download_images(client, note, dest_dir, title, progress_cb)
            return DownloadResult(title=title, thumbnail=thumb, file_path=path,
                                  size_bytes=os.path.getsize(path))

    @staticmethod
    def _resolve_page_url(client: httpx.Client, url: str) -> str:
        """短链跟随重定向；保留 xsec_token 等分享校验参数（去掉会 404/登录墙）。"""
        resp = client.get(url)
        final = str(resp.url)
        return final if "xiaohongshu.com" in final else url

    @staticmethod
    def _note_id_from_url(url: str) -> Optional[str]:
        match = re.search(r"/(?:explore|discovery/item)/([0-9a-f]{24})", url)
        return match.group(1) if match else None

    @staticmethod
    def _find_note(html: str, note_id: str) -> Optional[dict]:
        match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>",
                          html, re.DOTALL)
        if not match:
            return None
        try:
            # 页面 JSON 含非标准 undefined 值，先规范为 null
            blob = re.sub(r":\s*undefined([,}])", r":null\1", match.group(1))
            state = json.loads(blob)
        except json.JSONDecodeError:
            return None
        note_map = state.get("note", {}).get("noteDetailMap", {})
        note = note_map.get(note_id, {}).get("note")
        if not note:
            # 兼容旧版字段结构：map 键名可能不是 note_id，按 noteId 字段匹配
            for entry in note_map.values():
                if not isinstance(entry, dict):
                    continue
                candidate = entry.get("note")
                if isinstance(candidate, dict) and candidate.get("noteId") == note_id:
                    note = candidate
                    break
        return note if isinstance(note, dict) else None

    @staticmethod
    def _cover(note: dict) -> Optional[str]:
        images = note.get("imageList") or []
        if images:
            return images[0].get("urlDefault") or images[0].get("url")
        return None

    @staticmethod
    def _video_stream(note: dict) -> Optional[str]:
        try:
            streams = note["video"]["media"]["stream"]
            for codec in ("h264", "h265", "av1"):
                items = streams.get(codec) or []
                if items:
                    return items[0].get("masterUrl") or items[0].get("backupUrls", [None])[0]
        except (KeyError, IndexError, TypeError):
            return None
        return None

    def _download_video(self, client: httpx.Client, note: dict, dest_dir: str,
                        title: str, progress_cb: ProgressCallback) -> str:
        stream = self._video_stream(note)
        if not stream:
            raise DownloadError("笔记是视频类型，但未解析到视频流（可能需要登录）")
        path = os.path.join(dest_dir, f"{title}.mp4")
        self._stream_to_file(client, stream, path, progress_cb)
        return path

    def _download_images(self, client: httpx.Client, note: dict, dest_dir: str,
                         title: str, progress_cb: ProgressCallback) -> str:
        images = note.get("imageList") or []
        if not images:
            raise DownloadError("笔记没有可下载的图片或视频")
        saved: list[str] = []
        total = len(images)
        for i, img in enumerate(images):
            url = img.get("urlDefault") or img.get("url")
            if not url:
                continue
            ext = ".jpg"
            if ".png" in url.split("?")[0].lower():
                ext = ".png"
            elif ".webp" in url.split("?")[0].lower():
                ext = ".webp"
            path = os.path.join(dest_dir, f"{i + 1:02d}{ext}")
            self._stream_to_file(client, url, path, None)
            saved.append(path)
            progress_cb((i + 1) / total * 100, None, None)
        if not saved:
            raise DownloadError("图片下载失败（链接可能已失效）")
        zip_path = os.path.join(dest_dir, f"{title}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for path in saved:
                zf.write(path, os.path.basename(path))
                os.remove(path)
        return zip_path

    @staticmethod
    def _stream_to_file(client: httpx.Client, url: str, path: str,
                        progress_cb: Optional[ProgressCallback]) -> None:
        with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                raise DownloadError(
                    f"小红书媒体链接下载失败（HTTP {resp.status_code}），可能需要登录")
            total = int(resp.headers.get("content-length") or 0)
            done = 0
            with open(path, "wb") as fh:
                for chunk in resp.iter_bytes(65536):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress_cb and total:
                        progress_cb(min(done / total * 100, 100.0), None, None)
        if progress_cb:
            progress_cb(100.0, None, None)


# -------------------------------------------------------------------- factory

def build_engine(url: str, config: Optional[EngineConfig] = None) -> Engine:
    """按 URL 路由到适配器：小红书 -> XhsEngine，抖音 -> DouyinEngine，其余 -> YtDlpEngine。"""
    from .platforms import detect_platform

    cfg = config or EngineConfig()
    platform = detect_platform(url)
    if platform == "xhs":
        return XhsEngine(cfg)
    if platform == "douyin":
        from .douyin import DouyinEngine
        return DouyinEngine(cfg)
    return YtDlpEngine(cfg)
