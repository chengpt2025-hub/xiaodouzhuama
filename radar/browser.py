"""无头浏览器游客抓取（抖音 / 小红书）。

思路：用 Playwright 打开平台网页，以游客身份访问，让页面自己的 JS 计算签名
（抖音 a_bogus / msToken，小红书 X-s / X-t），我们只监听页面发出的接口响应，
从里面拿 JSON。全程不登录，不需要逆向签名算法，平台改算法也不受影响。
平台对游客的限制随时会变：拿不到数据时只记录原因并跳过，不影响其他平台。
"""
import json
import os
import time
import urllib.parse
from datetime import datetime, timezone

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || {runtime: {}};
"""


def _ts(sec):
    sec = int(sec or 0)
    if sec > 1e12:  # 毫秒
        sec //= 1000
    return datetime.fromtimestamp(sec, tz=timezone.utc)


class Browser:
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        self.ctx = self.browser.new_context(
            user_agent=UA, locale="zh-CN", timezone_id="Asia/Shanghai",
            viewport={"width": 1366, "height": 900})
        self.ctx.add_init_script(STEALTH)
        return self

    def __exit__(self, *a):
        try:
            self.browser.close()
        finally:
            self._pw.stop()

    def capture(self, url, match, scrolls=3, wait=2.5):
        """打开 url，收集 URL 中包含 match 任一片段的 JSON 响应。"""
        got = []
        page = self.ctx.new_page()

        def on_resp(resp):
            if any(m in resp.url for m in match):
                try:
                    got.append(resp.json())
                except Exception:  # noqa: BLE001
                    pass

        page.on("response", on_resp)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(wait)
            for sel in ("[class*=login] [class*=close]", ".close-button", "[aria-label=关闭]"):
                try:
                    page.locator(sel).first.click(timeout=800)
                except Exception:  # noqa: BLE001
                    pass
            for _ in range(scrolls):
                page.mouse.wheel(0, 2500)
                time.sleep(wait)
            html = page.content()
        finally:
            page.close()
        return got, html


# ---------------------------------------------------------------- 抖音 ----
def fetch_douyin(keywords, since, Post):
    out, seen = [], set()
    max_videos = int(os.getenv("RADAR_DOUYIN_VIDEOS", "8"))
    with Browser() as b:
        b.capture("https://www.douyin.com/", [], scrolls=0, wait=3)  # 先拿游客 ttwid / msToken
        videos = []
        for kw in keywords:
            q = urllib.parse.quote(kw)
            got, _ = b.capture(f"https://www.douyin.com/search/{q}?type=video&publish_time=1&sort_type=2",
                               ["/aweme/v1/web/search/item", "/aweme/v1/web/general/search"], scrolls=2)
            for j in got:
                rows = j.get("aweme_list") or [x.get("aweme_info") for x in (j.get("data") or []) if isinstance(x, dict)]
                for a in rows or []:
                    if not a or a.get("aweme_id") in seen:
                        continue
                    seen.add(a["aweme_id"])
                    t = _ts(a.get("create_time"))
                    url = f"https://www.douyin.com/video/{a['aweme_id']}"
                    desc = a.get("desc", "")
                    if t >= since:
                        out.append(Post("抖音", url, desc, t, (a.get("author") or {}).get("nickname", ""), desc, True))
                        videos.append((a["aweme_id"], desc))
        if not videos and not out:
            raise RuntimeError("抖音游客搜索没有返回结果（可能被要求登录或滑块验证）")
        for aid, desc in videos[:max_videos]:
            url = f"https://www.douyin.com/video/{aid}"
            got, _ = b.capture(url, ["/aweme/v1/web/comment/list"], scrolls=3, wait=2)
            for j in got:
                for c in j.get("comments") or []:
                    t = _ts(c.get("create_time"))
                    if t < since:
                        continue
                    subs = [x.get("text", "") for x in (c.get("reply_comment") or [])]
                    out.append(Post("抖音评论", f"{url}?cid={c.get('cid')}", c.get("text", ""), t,
                                    (c.get("user") or {}).get("nickname", ""), desc, True, subs))
    return out


# -------------------------------------------------------------- 小红书 ----
def fetch_xiaohongshu(keywords, since, Post):
    out, seen = [], set()
    max_notes = int(os.getenv("RADAR_XHS_NOTES", "8"))
    with Browser() as b:
        b.capture("https://www.xiaohongshu.com/explore", [], scrolls=0, wait=3)  # 先拿游客 a1 / webId
        notes = []
        for kw in keywords:
            q = urllib.parse.quote(kw)
            got, _ = b.capture(f"https://www.xiaohongshu.com/search_result?keyword={q}&source=web_search_result_notes&type=51",
                               ["/api/sns/web/v1/search/notes"], scrolls=2)
            for j in got:
                for it in (j.get("data") or {}).get("items") or []:
                    nid = it.get("id")
                    if not nid or nid in seen or it.get("model_type") != "note":
                        continue
                    seen.add(nid)
                    notes.append((nid, it.get("xsec_token", ""), (it.get("note_card") or {}).get("display_title", "")))
        if not notes:
            raise RuntimeError("小红书游客搜索没有返回结果（搜索可能要求登录）")
        for nid, tok, title in notes[:max_notes]:
            url = f"https://www.xiaohongshu.com/explore/{nid}?xsec_token={urllib.parse.quote(tok)}&xsec_source=pc_search"
            got, html = b.capture(url, ["/api/sns/web/v2/comment/page", "/api/sns/web/v1/feed"], scrolls=2, wait=2)
            for j in got:
                d = j.get("data") or {}
                for it in d.get("items") or []:  # 笔记正文
                    n = it.get("note_card") or {}
                    t = _ts(n.get("time"))
                    if t >= since:
                        out.append(Post("小红书", url, f"{n.get('title', '')} {n.get('desc', '')}", t,
                                        (n.get("user") or {}).get("nickname", ""), title, True))
                for c in d.get("comments") or []:  # 评论
                    t = _ts(c.get("create_time"))
                    if t < since:
                        continue
                    subs = [x.get("content", "") for x in (c.get("sub_comments") or [])]
                    out.append(Post("小红书评论", url, c.get("content", ""), t,
                                    (c.get("user_info") or {}).get("nickname", ""), title, True, subs))
            if not got and "__INITIAL_STATE__" in html:  # 退路：页面直出的笔记正文
                try:
                    raw = html.split("window.__INITIAL_STATE__=")[1].split("</script>")[0].replace("undefined", "null")
                    st = json.loads(raw)
                    n = (st.get("note", {}).get("noteDetailMap", {}).get(nid, {}) or {}).get("note", {})
                    t = _ts(n.get("time"))
                    if n and t >= since:
                        out.append(Post("小红书", url, f"{n.get('title', '')} {n.get('desc', '')}", t,
                                        (n.get("user") or {}).get("nickname", ""), title, True))
                except Exception:  # noqa: BLE001
                    pass
    return out
