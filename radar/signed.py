"""签名法游客抓取：抖音、小红书（纯 Python，不开浏览器）。

参考的开源项目：
- 抖音：Johnserf-Seed/f2 的 a_bogus 算法（radar/vendor/abogus.py）+ 字节公开的 ttwid 游客注册接口
- 小红书：Cloxl/xhshow（纯 Python 生成 x-s / x-t 等签名）+ 小红书网页端的游客激活接口
- 浏览器 TLS 指纹：lexiforest/curl_cffi（模拟 Chrome 的 TLS/HTTP2 指纹）

实测（2026-11-27）：
- 抖音：游客签名后，评论 / 回复接口可用；搜索接口对游客一律返回“请先登录”，与签名无关。
  所以先用全网检索找到相关的抖音作品，再用签名接口按时间抓它们的评论和回复。
- 小红书：游客激活后，笔记详情接口可用；搜索（-104）和评论（406）接口对游客关闭。
  所以先用全网检索找到相关笔记，能拿到 xsec_token 的读详情，否则读页面直出数据。
"""
import json
import os
import random
import re
import string
import sys
import time
import urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from curl_cffi import requests as cr  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def _ts(sec):
    sec = int(sec or 0)
    if sec > 1e12:
        sec //= 1000
    return datetime.fromtimestamp(sec, tz=timezone.utc)


def discover(queries, host_words):
    """用全网检索（ddgs + SearXNG）找某个平台的链接。"""
    from web import search_ddgs, search_searxng
    urls = []
    for fn in (search_ddgs, search_searxng):
        try:
            for r in fn(queries):
                u = r.get("url") or ""
                if any(h in u for h in host_words):
                    urls.append(u)
        except Exception as e:  # noqa: BLE001
            print(f"  [发现] {fn.__name__}: {e}")
    extra = os.getenv("RADAR_EXTRA_URLS", "")
    urls += [u.strip() for u in extra.split(",") if any(h in u for h in host_words)]
    return list(dict.fromkeys(urls))


# ---------------------------------------------------------------- 抖音 ----
class Douyin:
    def __init__(self):
        from vendor.abogus import ABogus
        self.ABogus = ABogus
        self.s = cr.Session(impersonate="chrome")
        r = self.s.post("https://ttwid.bytedance.com/ttwid/union/register/", json={
            "region": "cn", "aid": 1768, "needFid": False, "service": "www.ixigua.com",
            "migrate_info": {"ticket": "", "source": "node"}, "cbUrlProtocol": "https", "union": True}, timeout=15)
        self.s.cookies.set("ttwid", r.cookies.get("ttwid") or "", domain=".douyin.com")
        self.base = {
            "device_platform": "webapp", "aid": "6383", "channel": "channel_pc_web", "pc_client_type": "1",
            "version_code": "190500", "version_name": "19.5.0", "cookie_enabled": "true",
            "screen_width": "1920", "screen_height": "1080", "browser_language": "zh-CN",
            "browser_platform": "Win32", "browser_name": "Chrome", "browser_version": "130.0.0.0",
            "browser_online": "true", "engine_name": "Blink", "engine_version": "130.0.0.0",
            "os_name": "Windows", "os_version": "10", "cpu_core_num": "12", "device_memory": "8",
            "platform": "PC", "downlink": "10", "effective_type": "4g", "round_trip_time": "0",
            "msToken": "".join(random.choices(string.ascii_letters + string.digits + "-_", k=182)),
        }

    def get(self, path, extra):
        q = urllib.parse.urlencode({**self.base, **extra})
        ab = self.ABogus(user_agent=UA, options=[0, 1, 14]).generate_abogus(q)
        ab = ab[1] if isinstance(ab, tuple) else ab
        r = self.s.get(f"https://www.douyin.com{path}?{q}&a_bogus={urllib.parse.quote(ab)}",
                       headers={"User-Agent": UA, "Referer": "https://www.douyin.com/"}, timeout=15)
        return r.json()

    def resolve(self, url):
        """把各种抖音链接（含 v.douyin.com 短链）解析成作品 ID。"""
        m = re.search(r"(?:video|note|modal_id=|aweme_id=|share/video/)/?(\d{15,21})", url)
        if m:
            return m.group(1)
        if "v.douyin.com" in url or "iesdouyin.com" in url:
            try:
                r = self.s.get(url, allow_redirects=True, timeout=10, headers={"User-Agent": UA})
                m = re.search(r"(?:video|note)/(\d{15,21})", str(r.url))
                return m.group(1) if m else None
            except Exception:  # noqa: BLE001
                return None
        return None


def fetch_douyin(keywords, since, Post):
    dy = Douyin()
    urls = discover([f"抖音 {k}" for k in keywords] + [f"site:douyin.com {keywords[0]}"],
                    ("douyin.com", "iesdouyin.com"))
    ids = list(dict.fromkeys(i for i in (dy.resolve(u) for u in urls) if i))
    ids += [i for i in os.getenv("RADAR_DOUYIN_IDS", "").split(",") if i.strip()]
    if not ids:
        raise RuntimeError("全网检索暂未发现相关抖音作品（抖音搜索对游客关闭，需靠全网检索发现作品）")
    out = []
    for aid in ids[: int(os.getenv("RADAR_DOUYIN_VIDEOS", "15"))]:
        url = f"https://www.douyin.com/video/{aid}"
        try:
            j = dy.get("/aweme/v1/web/comment/list/", {"aweme_id": aid, "cursor": "0", "count": "50", "item_type": "0"})
        except Exception as e:  # noqa: BLE001
            print(f"  [抖音] 作品 {aid} 评论失败: {e}")
            continue
        for c in j.get("comments") or []:
            t = _ts(c.get("create_time"))
            subs = []
            if int(c.get("reply_comment_total") or 0) > 0:
                try:
                    rj = dy.get("/aweme/v1/web/comment/list/reply/",
                                {"item_id": aid, "comment_id": c["cid"], "cursor": "0", "count": "20", "item_type": "0"})
                    for x in rj.get("comments") or []:
                        subs.append(x.get("text", ""))
                        xt = _ts(x.get("create_time"))
                        if xt >= since:
                            out.append(Post("抖音评论", url, x.get("text", ""), xt, "", "", True))
                except Exception:  # noqa: BLE001
                    pass
            if t >= since:
                out.append(Post("抖音评论", url, c.get("text", ""), t, "", "", True, subs))
        time.sleep(0.5)
    return out


# -------------------------------------------------------------- 小红书 ----
class Xhs:
    def __init__(self):
        from xhshow import Xhshow
        self.c = Xhshow()
        self.a1 = self.c.generate_a1()
        self.wid = self.c.generate_web_id(self.a1)
        self.s = cr.Session(impersonate="chrome")
        for k, v in {"a1": self.a1, "webId": self.wid}.items():
            self.s.cookies.set(k, v, domain=".xiaohongshu.com")
        self.H = {"origin": "https://www.xiaohongshu.com", "referer": "https://www.xiaohongshu.com/",
                  "content-type": "application/json;charset=UTF-8"}
        self.post("/api/sns/web/v1/login/activate", {})  # 游客会话

    def ck(self):
        d = dict(self.s.cookies.get_dict())
        d.update({"a1": self.a1, "webId": self.wid})
        return d

    def post(self, uri, p):
        h = self.c.sign_headers_post(uri, self.ck(), payload=p)
        body = json.dumps(p, separators=(",", ":"), ensure_ascii=False).encode()
        return self.s.post("https://edith.xiaohongshu.com" + uri, data=body, headers={**self.H, **h}, timeout=15).json()


def fetch_xiaohongshu(keywords, since, Post):
    x = Xhs()
    urls = discover([f"小红书 {k}" for k in keywords] + [f"site:xiaohongshu.com {keywords[0]}"],
                    ("xiaohongshu.com", "xhslink.com"))
    out = []
    for u in urls[: int(os.getenv("RADAR_XHS_NOTES", "15"))]:
        if "xhslink.com" in u:
            try:
                u = str(x.s.get(u, allow_redirects=True, timeout=10).url)
            except Exception:  # noqa: BLE001
                continue
        m = re.search(r"(?:explore|discovery/item|item)/([0-9a-f]{24})", u)
        if not m:
            continue
        nid = m.group(1)
        tok = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("xsec_token", [""])[0]
        n = None
        if tok:
            j = x.post("/api/sns/web/v1/feed", {"source_note_id": nid, "image_formats": ["jpg", "webp", "avif"],
                                                "extra": {"need_body_topic": "1"}, "xsec_source": "pc_search",
                                                "xsec_token": tok})
            items = (j.get("data") or {}).get("items") or []
            n = (items[0].get("note_card") if items else None)
        if not n:
            try:
                html = x.s.get(u, timeout=15).text
                raw = html.split("window.__INITIAL_STATE__=")[1].split("</script>")[0].replace("undefined", "null")
                st = json.loads(raw)
                n = ((st.get("note") or {}).get("noteDetailMap") or {}).get(nid, {}).get("note")
            except Exception:  # noqa: BLE001
                n = None
        if n:
            t = _ts(n.get("time") or n.get("last_update_time"))
            if t >= since:
                out.append(Post("小红书", f"https://www.xiaohongshu.com/explore/{nid}",
                                f"{n.get('title', '')} {n.get('desc', '')}", t, "", n.get("title", ""), True))
        time.sleep(0.5)
    if not urls:
        raise RuntimeError("全网检索暂未发现相关小红书笔记（小红书搜索对游客关闭，需靠全网检索发现笔记）")
    return out
