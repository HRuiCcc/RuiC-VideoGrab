"""DouyinEngine 提取纯函数测试：aweme_detail fixture 来自真实抖音 API 结构。"""
import pytest

from backend.douyin import DouyinEngine, extract_media
from backend.engine import DownloadError

VIDEO_AWEME = {
    "desc": "看了这期还不会部署网站我真没招了",
    "author": {"nickname": "测试作者"},
    "video": {
        "play_addr": {"url_list": ["https://aweme.snssdk.com/aweme/v1/playwm/?video_id=v0xxx&ratio=720p"]},
        "cover": {"url_list": ["https://p3-sign.douyinpic.com/cover.jpg"]},
    },
    "images": None,
}

IMAGES_AWEME = {
    "desc": "九宫格图集",
    "author": {"nickname": "图集作者"},
    "video": {},
    "images": [
        {"url_list": ["https://p3-sign.douyinpic.com/1.jpg"]},
        {"url_list": ["https://p3-sign.douyinpic.com/2.jpg"]},
    ],
}


class TestExtractMedia:
    def test_video_aweme_yields_watermark_free_url(self):
        spec = extract_media(VIDEO_AWEME)
        assert spec.kind == "video"
        assert spec.title == "看了这期还不会部署网站我真没招了"
        assert spec.cover == "https://p3-sign.douyinpic.com/cover.jpg"
        # 无水印：playwm -> play，720p -> 1080p
        assert "playwm" not in spec.video_url
        assert "/aweme/v1/play/" in spec.video_url
        assert "ratio=1080p" in spec.video_url

    def test_images_aweme_collects_all_images(self):
        spec = extract_media(IMAGES_AWEME)
        assert spec.kind == "images"
        assert len(spec.image_urls) == 2
        assert spec.video_url is None

    def test_empty_aweme_raises_download_error(self):
        with pytest.raises(DownloadError, match="没有可下载"):
            extract_media({"video": {}, "images": None, "desc": "x"})

    def test_images_take_precedence_only_without_video(self):
        aweme = dict(IMAGES_AWEME)
        aweme["video"] = {"play_addr": {"url_list": ["https://a/v/playwm/?video_id=v0&ratio=720p"]}}
        spec = extract_media(aweme)
        assert spec.kind == "video"


class TestVideoId:
    def test_full_url(self):
        assert DouyinEngine._video_id("https://www.douyin.com/video/7671175696995159338") \
            == "7671175696995159338"

    def test_iesdouyin_url(self):
        assert DouyinEngine._video_id("https://www.iesdouyin.com/share/video/7671175696995159338/") \
            == "7671175696995159338"

    def test_short_link_resolves_via_redirect(self, monkeypatch):
        import httpx

        class FakeResp:
            url = "https://www.iesdouyin.com/share/video/7671175696995159338/"

        def fake_get(*a, **kw):
            return FakeResp()

        monkeypatch.setattr(httpx, "get", fake_get)
        assert DouyinEngine._video_id("https://v.douyin.com/AbCdEf/") == "7671175696995159338"
