"""切片1：平台识别纯函数。预期值来自真实平台域名/路径规约，与实现无关。"""
from backend.platforms import detect_platform, extract_urls


class TestDetectPlatform:
    def test_youtube(self):
        assert detect_platform("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "youtube"
        assert detect_platform("https://youtu.be/dQw4w9WgXcQ") == "youtube"
        assert detect_platform("https://m.youtube.com/shorts/abc123") == "youtube"

    def test_bilibili(self):
        assert detect_platform("https://www.bilibili.com/video/BV1xx411c7mD") == "bilibili"
        assert detect_platform("https://b23.tv/abc123") == "bilibili"

    def test_douyin(self):
        assert detect_platform("https://www.douyin.com/video/7123456789012345678") == "douyin"
        assert detect_platform("https://v.douyin.com/abcDEF/") == "douyin"

    def test_tiktok(self):
        assert detect_platform("https://www.tiktok.com/@user/video/7123456789012345678") == "tiktok"
        assert detect_platform("https://vm.tiktok.com/abc123/") == "tiktok"

    def test_xiaohongshu(self):
        assert detect_platform("https://www.xiaohongshu.com/explore/64ab00000000000001000000") == "xhs"
        assert detect_platform("https://www.xiaohongshu.com/discovery/item/64ab00000000000001000000") == "xhs"
        assert detect_platform("https://xhslink.com/a/AbC123") == "xhs"

    def test_instagram(self):
        assert detect_platform("https://www.instagram.com/reel/Cxyz123/") == "instagram"
        assert detect_platform("https://www.instagram.com/p/Cxyz123/") == "instagram"

    def test_twitter_and_x(self):
        assert detect_platform("https://twitter.com/user/status/123456789") == "twitter"
        assert detect_platform("https://x.com/user/status/123456789") == "twitter"

    def test_weibo(self):
        assert detect_platform("https://weibo.com/123456/AbCdEf") == "weibo"
        assert detect_platform("https://m.weibo.cn/detail/123456") == "weibo"

    def test_kuaishou(self):
        assert detect_platform("https://www.kuaishou.com/short-video/3xabc") == "kuaishou"

    def test_wechat_channels(self):
        assert detect_platform("https://channels.weixin.qq.com/feed/abc") == "wechat"

    def test_unknown_falls_back_to_other(self):
        assert detect_platform("https://example.com/watch?v=1") == "other"
        assert detect_platform("随便一段文字") == "other"
        assert detect_platform("") == "other"


class TestExtractUrls:
    def test_single_url(self):
        assert extract_urls("https://youtu.be/abc123") == ["https://youtu.be/abc123"]

    def test_multiple_urls_per_line(self):
        text = "https://youtu.be/aaa\nhttps://www.bilibili.com/video/BV1bb\n随便一行文字"
        assert extract_urls(text) == [
            "https://youtu.be/aaa",
            "https://www.bilibili.com/video/BV1bb",
        ]

    def test_url_with_chinese_text_around_it(self):
        text = "看这个 https://v.douyin.com/abcDEF/ 太好笑了"
        assert extract_urls(text) == ["https://v.douyin.com/abcDEF/"]

    def test_no_url_returns_empty(self):
        assert extract_urls("没有链接") == []
