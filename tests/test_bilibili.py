"""B站自举模块：缓存 TTL、失败降级、生成文件格式。fetch 注入假函数，不触网。"""
import os
import time

from backend.bilibili import ensure_bootstrap


def test_generates_cookie_file_when_fresh(tmp_path):
    path = ensure_bootstrap(str(tmp_path),
                            fetch=lambda: {"b_3": "B3VAL", "b_4": "B4VAL"})
    assert path is not None and os.path.exists(path)
    content = open(path).read()
    assert "buvid3\tB3VAL" in content
    assert "buvid4\tB4VAL" in content
    assert ".bilibili.com\tTRUE\t/" in content


def test_cached_file_is_reused_without_refetch(tmp_path):
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"b_3": "B3", "b_4": "B4"}

    first = ensure_bootstrap(str(tmp_path), fetch=fetch)
    second = ensure_bootstrap(str(tmp_path), fetch=fetch)
    assert first == second
    assert calls["n"] == 1


def test_expired_cache_is_refreshed(tmp_path):
    path = ensure_bootstrap(str(tmp_path),
                            fetch=lambda: {"b_3": "OLD", "b_4": "OLD"})
    old_mtime = time.time() - 8 * 3600
    os.utime(path, (old_mtime, old_mtime))
    path2 = ensure_bootstrap(str(tmp_path),
                             fetch=lambda: {"b_3": "NEW", "b_4": "NEW"})
    assert "buvid3\tNEW" in open(path2).read()


def test_fetch_failure_falls_back_to_old_cache(tmp_path):
    path = ensure_bootstrap(str(tmp_path),
                            fetch=lambda: {"b_3": "OLD", "b_4": "OLD"})
    old_mtime = time.time() - 8 * 3600
    os.utime(path, (old_mtime, old_mtime))
    path2 = ensure_bootstrap(str(tmp_path), fetch=lambda: (_ for _ in ()).throw(IOError("net down")))
    assert path2 == path  # 退回旧缓存而不是 None


def test_fetch_failure_with_no_cache_returns_none(tmp_path):
    assert ensure_bootstrap(str(tmp_path),
                            fetch=lambda: (_ for _ in ()).throw(IOError("net down"))) is None
