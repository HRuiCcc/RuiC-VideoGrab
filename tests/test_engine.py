"""切片3：引擎路由分发。小红书走 XhsEngine，其余全走 YtDlpEngine 兜底。"""
import pytest

from backend.engine import EngineConfig, XhsEngine, YtDlpEngine, build_engine


class TestEngineRouting:
    @pytest.mark.parametrize("url", [
        "https://www.xiaohongshu.com/explore/64ab00000000000001000000",
        "https://www.xiaohongshu.com/discovery/item/64ab00000000000001000000",
        "https://xhslink.com/a/AbC123",
    ])
    def test_xhs_urls_route_to_xhs_engine(self, url):
        assert isinstance(build_engine(url), XhsEngine)

    @pytest.mark.parametrize("url", [
        "https://www.douyin.com/video/7123456789012345678",
        "https://v.douyin.com/abcDEF/",
        "https://www.iesdouyin.com/share/video/7123456789012345678/",
    ])
    def test_douyin_urls_route_to_douyin_engine(self, url):
        from backend.douyin import DouyinEngine
        assert isinstance(build_engine(url), DouyinEngine)

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://www.tiktok.com/@user/video/7123456789012345678",
        "https://www.instagram.com/reel/Cxyz123/",
        "https://x.com/user/status/123456789",
        "https://weibo.com/123456/AbCdEf",
        "https://www.kuaishou.com/short-video/3xabc",
        "https://channels.weixin.qq.com/feed/abc",
        "https://example.com/whatever",  # 未知平台也走 yt-dlp 尝试
    ])
    def test_everything_else_routes_to_ytdlp(self, url):
        assert isinstance(build_engine(url), YtDlpEngine)


class TestEngineConfigDefaults:
    def test_build_engine_without_config_still_works(self):
        engine = build_engine("https://youtu.be/abc")
        assert engine.config.downloads_root == "downloads"
        assert engine.config.cookie_file is None

    def test_build_engine_honours_explicit_config(self):
        cfg = EngineConfig(downloads_root="/tmp/vg", cookie_file="/tmp/c.txt")
        engine = build_engine("https://xhslink.com/a/abc", config=cfg)
        assert engine.config is cfg
