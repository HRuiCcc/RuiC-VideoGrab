"""DouyinEngine：Playwright 真浏览器过风控 + aweme_detail 提取 + 直链下载。

无 cookie 可用（真 Chromium 内核过抖音风控）。fallback 说明见 download 错误文案。
"""
from __future__ import annotations

import asyncio
import os
import zipfile
from dataclasses import dataclass
from typing import Callable, List, Optional

import httpx

from .engine import DownloadError, DownloadResult, Engine, EngineConfig, ProgressCallback, _clean_filename


# ---------------------------------------------------------------- 提取纯函数

@dataclass
class MediaSpec:
    kind: str                    # "video" | "images"
    title: str
    cover: Optional[str]
    video_url: Optional[str]     # 无水印直链
    image_urls: List[str]


def extract_media(aweme_detail: dict) -> MediaSpec:
    """从 aweme_detail 提媒体信息。失败抛 DownloadError。"""
    video = aweme_detail.get("video") or {}
    play_addr = video.get("play_addr") or {}
    url_list = play_addr.get("url_list") or []
    video_url = url_list[0] if url_list else None
    if video_url:
        video_url = video_url.replace("playwm", "play").replace("&ratio=720p", "&ratio=1080p")
    images = [u for u in ((img.get("url_list") or [None])[0]
                          for img in (aweme_detail.get("images") or [])) if u]
    cover = (video.get("cover") or {}).get("url_list") or [None]
    title = (aweme_detail.get("desc") or "").strip() or "抖音视频"
    author = (aweme_detail.get("author") or {}).get("nickname") or ""
    if not video_url and not images:
        raise DownloadError("抖音返回了数据，但没有可下载的视频/图片（可能被风控，请稍后重试）")
    return MediaSpec(
        kind="images" if images and not video_url else "video",
        title=title, cover=cover[0], video_url=video_url, image_urls=images)


# ---------------------------------------------------------------- 引擎

_CAPTCHA_HINTS = ("验证码", "captcha", "verify", "sec_sdk", "滑动")


class DouyinEngine(Engine):
    """抖音适配器：headless Chromium 打开视频页，拦截 aweme/detail 响应。"""

    def __init__(self, config: EngineConfig):
        self.config = config

    async def download(self, url: str, dest_dir: str,
                       progress_cb: ProgressCallback) -> DownloadResult:
        return await asyncio.to_thread(self._download_sync, url, dest_dir, progress_cb)

    # ---- 同步主流程（跑在线程里）----

    def _download_sync(self, url: str, dest_dir: str,
                       progress_cb: ProgressCallback) -> DownloadResult:
        os.makedirs(dest_dir, exist_ok=True)
        aweme = self._fetch_aweme(url)
        spec = extract_media(aweme)
        title = _clean_filename(spec.title)
        if spec.kind == "video":
            path = os.path.join(dest_dir, f"{title}.mp4")
            self._download_url(spec.video_url, path, progress_cb)
        else:
            path = self._download_images(spec.image_urls, dest_dir, title, progress_cb)
        return DownloadResult(title=spec.title, thumbnail=spec.cover,
                              file_path=path, size_bytes=os.path.getsize(path))

    def _fetch_aweme(self, url: str) -> dict:
        """Playwright 打开视频页并拦截 aweme/detail 响应；失败给出可操作指引。"""
        from playwright.sync_api import sync_playwright
        video_id = self._video_id(url)
        page_url = f"https://www.douyin.com/video/{video_id}"
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=[
                    "--disable-blink-features=AutomationControlled", "--no-sandbox"])
                try:
                    ctx = browser.new_context(
                        user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                                    "Chrome/126.0.0.0 Safari/537.36"),
                        viewport={"width": 1280, "height": 800}, locale="zh-CN")
                    page = ctx.new_page()
                    result: dict = {}

                    def on_response(resp):
                        if "aweme/v1/web/aweme/detail" in resp.url:
                            try:
                                body = resp.json()
                                if body.get("aweme_detail"):
                                    result.setdefault("aweme", body["aweme_detail"])
                            except Exception:
                                pass

                    page.on("response", on_response)
                    page.goto(page_url, wait_until="domcontentloaded", timeout=40000)
                    page.wait_for_timeout(9000)
                    if result.get("aweme"):
                        return result["aweme"]
                    html = page.content()
                    for hint in _CAPTCHA_HINTS:
                        if hint in html:
                            raise DownloadError(
                                "抖音触发了验证码风控：稍后重试，或到「设置」配置浏览器 cookies")
                    raise DownloadError("未能从页面获取视频数据（可能被风控，请稍后重试）")
                finally:
                    browser.close()
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError(
                f"抖音解析失败：{str(exc)[:120]}。可尝试到「设置」配置抖音 cookies 后重试") from exc

    @staticmethod
    def _video_id(url: str) -> str:
        import re
        m = re.search(r"(?:/video/|video/|modal_id=)(\d{15,})", url)
        if m:
            return m.group(1)
        # 短链：跟随重定向拿 id
        try:
            resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True,
                             timeout=20)
            m = re.search(r"/video/(\d{15,})", str(resp.url))
            if m:
                return m.group(1)
        except Exception:
            pass
        raise DownloadError("无法解析抖音链接，请检查链接是否完整")

    # ---- 下载助手 ----

    def _download_url(self, url: str, path: str,
                      progress_cb: ProgressCallback) -> None:
        headers = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/126.0.0.0 Safari/537.36"),
                   "Referer": "https://www.douyin.com/"}
        with httpx.stream("GET", url, headers=headers, timeout=60, follow_redirects=True) as r:
            if r.status_code != 200:
                raise DownloadError(f"抖音视频直链下载失败（HTTP {r.status_code}）")
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with open(path, "wb") as fh:
                for chunk in r.iter_bytes(65536):
                    fh.write(chunk)
                    done += len(chunk)
                    if total:
                        progress_cb(min(done / total * 100, 100.0), None, None)
        progress_cb(100.0, None, None)

    def _download_images(self, urls: List[str], dest_dir: str, title: str,
                         progress_cb: ProgressCallback) -> str:
        saved = []
        total = len(urls)
        for i, u in enumerate(urls):
            path = os.path.join(dest_dir, f"{i + 1:02d}.jpg")
            self._download_url(u, path, None)
            saved.append(path)
            progress_cb((i + 1) / total * 100, None, None)
        zip_path = os.path.join(dest_dir, f"{title}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for p in saved:
                zf.write(p, os.path.basename(p))
                os.remove(p)
        return zip_path
