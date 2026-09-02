"""成品路径选择 + 412 风控判定 + 重试环。全部不触网。"""
import asyncio

import pytest
import yt_dlp

from backend import engine as engine_mod
from backend.engine import DownloadError, EngineConfig, YtDlpEngine


class TestPickFinalPath:
    def test_prefers_existing_finished_file(self, tmp_path):
        final = tmp_path / "final.mp4"
        final.write_bytes(b"x")
        path = YtDlpEngine._pick_final_path(str(tmp_path),
                                            [str(tmp_path / "gone.m4a"), str(final)])
        assert path == str(final)

    def test_skips_intermediate_fragment_files(self, tmp_path):
        frag = tmp_path / "title.f30232.m4a"  # 合并后残留的分片命名
        frag.write_bytes(b"x")
        final = tmp_path / "title.mp4"
        final.write_bytes(b"y")
        path = YtDlpEngine._pick_final_path(str(tmp_path), [str(frag)])
        assert path == str(final)

    def test_falls_back_to_newest_media_when_finished_empty(self, tmp_path):
        (tmp_path / "a.mp4").write_bytes(b"a")
        (tmp_path / "b.mp4").write_bytes(b"b")
        path = YtDlpEngine._pick_final_path(str(tmp_path), [])
        assert path == str(tmp_path / "b.mp4")

    def test_find_media_excludes_fragments_and_parts(self, tmp_path):
        (tmp_path / "x.f123.m4a").write_bytes(b"frag")
        (tmp_path / "y.mp4.part").write_bytes(b"part")
        (tmp_path / "z.mp4").write_bytes(b"final")
        assert YtDlpEngine._find_media(str(tmp_path)) == str(tmp_path / "z.mp4")


class TestRiskControl:
    def test_412_detected(self):
        assert YtDlpEngine._is_risk_control("ERROR: HTTP Error 412: Precondition Failed")
        assert YtDlpEngine._is_risk_control("Precondition Failed (caused by HTTPError 412)")

    def test_other_errors_not_risk_control(self):
        assert not YtDlpEngine._is_risk_control("This video is unavailable")
        assert not YtDlpEngine._is_risk_control("Sign in to confirm your age")


class _FlakyYdl:
    """第一次抛 412 DownloadError，之后成功返回空 info。"""
    calls = 0

    def __init__(self, opts): ...
    def __enter__(self): return self
    def __exit__(self, *args): return False

    def extract_info(self, url, download=True):
        type(self).calls += 1
        if type(self).calls == 1:
            raise yt_dlp.utils.DownloadError("ERROR: HTTP Error 412: Precondition Failed")
        return {}


def test_risk_control_412_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod.yt_dlp, "YoutubeDL", _FlakyYdl)
    _FlakyYdl.calls = 0
    monkeypatch.setattr(YtDlpEngine, "_refresh_bootstrap", lambda self: None)
    monkeypatch.setattr(engine_mod.time, "sleep", lambda s: None)  # 测试不等退避
    (tmp_path / "out.mp4").write_bytes(b"x" * 5)

    engine = YtDlpEngine(EngineConfig(data_dir=str(tmp_path)))
    result = asyncio.run(engine.download("https://www.bilibili.com/video/BV123",
                                         str(tmp_path), lambda *a: None))
    assert result.file_path.endswith("out.mp4")
    assert _FlakyYdl.calls == 2  # 重试了一次后成功


def test_non_risk_control_error_is_not_retried(tmp_path, monkeypatch):
    class Boom:
        def __init__(self, opts): ...
        def __enter__(self): return self
        def __exit__(self, *args): return False

        def extract_info(self, url, download=True):
            raise yt_dlp.utils.DownloadError("This video is unavailable")

    monkeypatch.setattr(engine_mod.yt_dlp, "YoutubeDL", Boom)
    engine = YtDlpEngine(EngineConfig(data_dir=str(tmp_path)))
    with pytest.raises(DownloadError, match="视频不可用"):
        asyncio.run(engine.download("https://www.youtube.com/watch?v=x",
                                    str(tmp_path), lambda *a: None))
