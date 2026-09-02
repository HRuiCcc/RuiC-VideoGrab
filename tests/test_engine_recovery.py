"""切片4补：yt-dlp 合并后清理中间文件的已知竞态——成品已存在时应恢复为成功。"""
from backend import engine as engine_mod
from backend.engine import EngineConfig, YtDlpEngine


class _BoomYdl:
    """模拟 extract_info 抛 FileNotFoundError（合并后访问已删中间文件）。"""

    def __init__(self, opts): ...
    def __enter__(self): return self
    def __exit__(self, *args): return False

    def extract_info(self, url, download=True):
        raise FileNotFoundError("[Errno 2] No such file or directory: 'x.f30280.m4a'")


def test_postprocess_race_recovers_when_media_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod.yt_dlp, "YoutubeDL", _BoomYdl)
    (tmp_path / "out.mp4").write_bytes(b"x" * 10)
    engine = YtDlpEngine(EngineConfig())

    import asyncio
    result = asyncio.run(engine.download("https://a.example/v", str(tmp_path), lambda *a: None))
    assert result.file_path.endswith("out.mp4")
    assert result.size_bytes == 10


def test_postprocess_race_still_fails_when_no_media(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod.yt_dlp, "YoutubeDL", _BoomYdl)
    engine = YtDlpEngine(EngineConfig())

    import asyncio
    from backend.engine import DownloadError
    import pytest
    with pytest.raises(DownloadError):
        asyncio.run(engine.download("https://a.example/v", str(tmp_path), lambda *a: None))
