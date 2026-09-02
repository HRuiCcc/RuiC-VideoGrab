"""平台识别：URL -> 平台名。纯函数、无 IO，供引擎路由与前端展示使用。"""
from __future__ import annotations

import re

# 顺序即优先级：先匹配更具体的域名规则。边界 [./] 允许域名紧跟 https:// 之后。
_PLATFORM_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("youtube", re.compile(r"(^|[./])(youtube\.com|youtu\.be)($|[/?#])")),
    ("bilibili", re.compile(r"(^|[./])(bilibili\.com|b23\.tv)($|[/?#])")),
    ("douyin", re.compile(r"(^|[./])(douyin\.com|iesdouyin\.com)($|[/?#])")),
    ("tiktok", re.compile(r"(^|[./])(tiktok\.com)($|[/?#])")),
    ("xhs", re.compile(r"(^|[./])(xiaohongshu\.com|xhslink\.com)($|[/?#])")),
    ("instagram", re.compile(r"(^|[./])(instagram\.com)($|[/?#])")),
    ("twitter", re.compile(r"(^|[./])(twitter\.com|x\.com)($|[/?#])")),
    ("weibo", re.compile(r"(^|[./])(weibo\.com|weibo\.cn)($|[/?#])")),
    ("kuaishou", re.compile(r"(^|[./])(kuaishou\.com|gifshow\.com)($|[/?#])")),
    ("wechat", re.compile(r"(^|[./])(channels\.weixin\.qq\.com)($|[/?#])")),
]

_URL_RE = re.compile(r"https?://[^\s<>\"'，。；、！？【】]+")


def detect_platform(url: str) -> str:
    """返回平台小写名；不认识的一律 'other'（yt-dlp 仍会尝试下载）。"""
    url = (url or "").strip()
    for platform, pattern in _PLATFORM_RULES:
        if pattern.search(url):
            return platform
    return "other"


def extract_urls(text: str) -> list[str]:
    """从粘贴的多行文本里提出所有 http(s) 链接，保持出现顺序，去重。"""
    seen: set[str] = set()
    urls: list[str] = []
    for match in _URL_RE.findall(text or ""):
        url = match.rstrip(".,;:!?)]}>\"'")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls
