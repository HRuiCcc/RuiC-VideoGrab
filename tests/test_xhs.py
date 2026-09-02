"""XhsEngine 修复回归测试：xsec_token 保留 + 非标准 undefined JSON 解析。"""
from backend.engine import XhsEngine

HTML_WITH_UNDEFINED = """
<script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{"%s":{
"note":{"noteId":"%s","title":"带undefined的笔记","type":"video","desc":"x",
"firstVisitUrl":undefined,"user":{"nickname":"测试号"},
"video":{"media":{"stream":{"h264":[{"masterUrl":"https://sns-video-bd.xhscdn.com/v.mp4"}]}}},
"imageList":[{"urlDefault":"https://sns-img-bd.xhscdn.com/c.jpg"}]}}}},
"routers":undefined}</script>
"""


def test_find_note_handles_undefined_values():
    note = XhsEngine._find_note(HTML_WITH_UNDEFINED % ("id123", "id123"), "id123")
    assert note is not None
    assert note["title"] == "带undefined的笔记"
    assert note["type"] == "video"


def test_find_note_returns_none_for_other_id():
    assert XhsEngine._find_note(HTML_WITH_UNDEFINED % ("id123", "id123"), "nope") is None


def test_find_note_returns_none_for_garbage_html():
    assert XhsEngine._find_note("<html>没有数据</html>", "id123") is None


def test_note_id_from_url():
    u = "https://www.xiaohongshu.com/discovery/item/686b2c91000000002201cf63?xsec_token=abc"
    assert XhsEngine._note_id_from_url(u) == "686b2c91000000002201cf63"
    assert XhsEngine._note_id_from_url("https://www.xiaohongshu.com/explore/686b2c91000000002201cf63") \
        == "686b2c91000000002201cf63"
    assert XhsEngine._note_id_from_url("https://example.com/x") is None


class FakeClient:
    def __init__(self, final_url: str):
        self._final = final_url

    def get(self, url):
        class Resp:
            url = self._final
        return Resp()


def test_resolve_page_url_keeps_xsec_token_url():
    url = ("https://www.xiaohongshu.com/discovery/item/686b2c91000000002201cf63"
           "?xsec_token=ABC&xsec_source=pc_share")
    assert XhsEngine._resolve_page_url(FakeClient(url), url) == url
