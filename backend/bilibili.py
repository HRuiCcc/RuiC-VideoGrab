"""B站风控自举：用官方指纹接口生成 buvid3/buvid4 cookie，绕过 412 风控。

Interface:
    ensure_bootstrap(data_dir, fetch=...) -> str|None   返回可用 cookies.txt 路径

缓存 TTL 默认 6 小时；fetch 可注入以便测试。
"""
from __future__ import annotations

import os
import time
from typing import Callable, Optional

import httpx

SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"
CACHE_TTL_SECONDS = 6 * 3600
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")


def _fetch_spi() -> dict:
    resp = httpx.get(SPI_URL, headers={"User-Agent": USER_AGENT}, timeout=10)
    resp.raise_for_status()
    return (resp.json() or {}).get("data") or {}


def ensure_bootstrap(data_dir: str,
                     fetch: Callable[[], dict] = _fetch_spi,
                     max_age_seconds: int = CACHE_TTL_SECONDS) -> Optional[str]:
    """确保存在新鲜的 B站自举 cookies 文件；失败时退回旧缓存或 None。"""
    path = os.path.join(data_dir, "bilibili-bootstrap.txt")
    if os.path.exists(path) and \
            time.time() - os.path.getmtime(path) < max_age_seconds:
        return path
    try:
        data = fetch()
    except Exception:
        return path if os.path.exists(path) else None
    b3, b4 = data.get("b_3"), data.get("b_4")
    if not b3 or not b4:
        return path if os.path.exists(path) else None
    os.makedirs(data_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Netscape HTTP Cookie File\n")
        fh.write(f".bilibili.com\tTRUE\t/\tFALSE\t0\tbuvid3\t{b3}\n")
        fh.write(f".bilibili.com\tTRUE\t/\tFALSE\t0\tbuvid4\t{b4}\n")
    return path
