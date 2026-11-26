"""各社交/娱乐平台的免登录抓取源。

每个源都是一个函数，返回 Post 列表；任何异常都只影响该源本身，不影响其他源。
新增平台：写一个 fetch_xxx(keywords, since) 函数，并加到 SOURCES 里即可。
"""
import hashlib
import os
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 12


@dataclass
class Post:
    source: str            # 平台名，如 "B站"
    url: str               # 原帖链接
    text: str              # 正文（已去 HTML）
    posted_at: datetime    # 发布时间（UTC）
    author: str = ""
    title: str = ""        # 所属帖子/视频标题（评论时为父帖标题）
    is_topic: bool = False  # 所属帖子本身就是小豆邀请码主题
    replies: list = field(default_factory=list)  # 该条下面的回复文本，用来判断是否已被领走


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _ts(sec) -> datetime:
    return datetime.fromtimestamp(int(sec), tz=timezone.utc)


# ---------------------------------------------------------------- B 站 ----
_MIXIN = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
          33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
          26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
          20, 34, 44, 52]


class Bili:
    """B 站游客模式：buvid 游客指纹 + WBI 签名（与网页端相同的公开算法），无需登录。"""

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
        spi = self.s.get("https://api.bilibili.com/x/frontend/finger/spi", timeout=TIMEOUT).json()["data"]
        self.s.cookies.set("buvid3", spi["b_3"], domain=".bilibili.com")
        self.s.cookies.set("buvid4", spi["b_4"], domain=".bilibili.com")
        nav = self.s.get("https://api.bilibili.com/x/web-interface/nav", timeout=TIMEOUT).json()["data"]["wbi_img"]
        raw = (nav["img_url"].rsplit("/", 1)[1].split(".")[0] + nav["sub_url"].rsplit("/", 1)[1].split(".")[0])
        self.mixin = "".join(raw[i] for i in _MIXIN)[:32]

    def sign(self, params):
        p = dict(params)
        p["wts"] = int(time.time())
        p = {k: re.sub(r"[!'()*]", "", str(v)) for k, v in sorted(p.items())}
        p["w_rid"] = hashlib.md5((urllib.parse.urlencode(p) + self.mixin).encode()).hexdigest()
        return p

    def get(self, url, params, signed=False):
        r = self.s.get(url, params=self.sign(params) if signed else params, timeout=TIMEOUT)
        j = r.json()
        if j.get("code") != 0:
            raise RuntimeError(f"bilibili {url} code={j.get('code')} {j.get('message')}")
        return j.get("data") or {}


def fetch_bilibili(keywords, since):
    b = Bili()
    out, seen = [], set()
    max_videos = int(os.getenv("RADAR_BILI_VIDEOS", "12"))
    for kw in keywords:
        for stype in ("video", "article"):
            try:
                data = b.get("https://api.bilibili.com/x/web-interface/wbi/search/type",
                             {"search_type": stype, "keyword": kw, "order": "pubdate", "page": 1}, signed=True)
            except Exception as e:  # noqa: BLE001
                print(f"  [B站] 搜索 {kw}/{stype} 失败: {e}")
                continue
            for v in (data.get("result") or [])[:max_videos]:
                oid = v.get("aid") or v.get("id")
                pub = _ts(v.get("pubdate") or v.get("pub_time") or 0)
                if not oid or oid in seen or pub < since:
                    continue
                seen.add(oid)
                title = _clean(v.get("title"))
                if stype == "video":
                    url, rtype = f"https://www.bilibili.com/video/av{oid}", 1
                    body = _clean(v.get("description"))
                else:
                    url, rtype = f"https://www.bilibili.com/read/cv{oid}", 12
                    body = _clean(v.get("desc"))
                out.append(Post("B站", url, f"{title} {body}", pub, _clean(v.get("author") or ""), title, True))
                out.extend(_bili_comments(b, oid, rtype, url, title, since))
                time.sleep(0.4)
    return out


def _bili_comments(b, oid, rtype, url, title, since):
    posts = []
    try:
        data = b.get("https://api.bilibili.com/x/v2/reply/main",
                     {"type": rtype, "oid": oid, "mode": 2, "next": 0, "ps": 30})
    except Exception as e:  # noqa: BLE001
        print(f"  [B站] 评论 {oid} 失败: {e}")
        return posts
    for rp in data.get("replies") or []:
        t = _ts(rp["ctime"])
        if t < since:
            continue
        subs = [x["content"]["message"] for x in (rp.get("replies") or [])]
        posts.append(Post("B站评论", f"{url}#reply{rp['rpid']}", rp["content"]["message"], t,
                          rp.get("member", {}).get("uname", ""), title, True, subs))
        for x in rp.get("replies") or []:
            posts.append(Post("B站评论", f"{url}#reply{x['rpid']}", x["content"]["message"], _ts(x["ctime"]),
                              x.get("member", {}).get("uname", ""), title, True))
    return posts


# ---------------------------------------------------------------- 贴吧 ----
_TB_VER = "12.57.4.2"


def _tb_sign(params):
    """贴吧客户端公开签名：参数按 key 排序拼接 + "tiebaclient!!!" 取 MD5 大写。"""
    p = {k: str(v) for k, v in params.items()}
    raw = "".join(f"{k}={v}" for k, v in sorted(p.items())) + "tiebaclient!!!"
    p["sign"] = hashlib.md5(raw.encode()).hexdigest().upper()
    return p


def _tb_post(path, params):
    r = requests.post("http://c.tieba.baidu.com" + path,
                      data=_tb_sign({"_client_type": 2, "_client_version": _TB_VER, **params}),
                      headers={"User-Agent": "bdtb for Android " + _TB_VER}, timeout=TIMEOUT)
    j = r.json()
    if str(j.get("error_code", "0")) not in ("0", ""):
        raise RuntimeError(f"贴吧 {path} error_code={j.get('error_code')} {j.get('error_msg')}")
    return j


def _tb_text(content):
    return "".join(c.get("text", "") or c.get("link", "") for c in content or [])


def fetch_tieba(keywords, since):
    """贴吧：客户端接口签名法（免登录），按时间搜全吧帖子，再翻帖子楼层和楼中楼。"""
    out, threads = [], {}
    max_threads = int(os.getenv("RADAR_TIEBA_THREADS", "15"))
    for kw in keywords:
        try:
            j = _tb_post("/c/s/searchpost", {"word": kw, "pn": 1, "rn": 30, "sm": 1, "only_thread": 0})
            items = j.get("post_list") or []
        except Exception as e:  # noqa: BLE001  签名接口不通时退回网页移动端接口
            print(f"  [贴吧] 客户端接口失败，改用移动网页接口: {e}")
            r = requests.get("https://tieba.baidu.com/mo/q/search/thread",
                             params={"word": kw, "pn": 1, "rn": 30, "sm": 1},
                             headers={"User-Agent": UA}, timeout=TIMEOUT).json()
            items = (r.get("data") or {}).get("post_list") or []
        for it in items:
            t = _ts(it.get("time") or it.get("create_time") or 0)
            tid = str(it.get("tid"))
            title = _clean(it.get("title"))
            url = f"https://tieba.baidu.com/p/{tid}"
            if t >= since:
                author = (it.get("author") or {}).get("name_show") or (it.get("user") or {}).get("user_name", "")
                out.append(Post("百度贴吧", f"{url}?pid={it.get('pid')}#{it.get('pid')}",
                                f"{title} {_clean(it.get('content'))}", t, author, title, True))
            mt = _ts(it.get("modified_time") or it.get("time") or 0)
            if mt >= since and tid not in threads:
                threads[tid] = title
    for tid, title in list(threads.items())[:max_threads]:
        url = f"https://tieba.baidu.com/p/{tid}"
        try:
            j = _tb_post("/c/f/pb/page", {"kz": tid, "pn": 1, "rn": 50, "r": 1})  # r=1 倒序，最新楼层在前
        except Exception as e:  # noqa: BLE001
            print(f"  [贴吧] 帖子 {tid} 失败: {e}")
            continue
        for p in j.get("post_list") or []:
            t = _ts(p.get("time") or 0)
            subs = [(_tb_text(x.get("content")), _ts(x.get("time") or 0), x.get("id"))
                    for x in ((p.get("sub_post_list") or {}).get("sub_post_list") or [])]
            if t >= since:
                out.append(Post("贴吧楼层", f"{url}?pid={p.get('id')}#{p.get('id')}", _tb_text(p.get("content")), t,
                                "", title, True, [x[0] for x in subs]))
            for txt, st, sid in subs:
                if st >= since:
                    out.append(Post("贴吧楼层", f"{url}?pid={sid}#{sid}", txt, st, "", title, True))
        time.sleep(0.3)
    return out


# ---------------------------------------------------------------- 微博 ----
def fetch_weibo(keywords, since):
    """微博搜索目前强制登录。只有在仓库 Secret 里配置了 WEIBO_COOKIE 才会启用（可选）。"""
    cookie = os.getenv("WEIBO_COOKIE", "").strip()
    if not cookie:
        raise RuntimeError("微博搜索需要登录，未配置 WEIBO_COOKIE，跳过（可选源）")
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Cookie": cookie, "Referer": "https://m.weibo.cn/",
                      "MWeibo-Pwa": "1", "X-Requested-With": "XMLHttpRequest"})
    out = []
    for kw in keywords:
        j = s.get("https://m.weibo.cn/api/container/getIndex",
                  params={"containerid": f"100103type=61&q={kw}&t=", "page_type": "searchall"},
                  timeout=TIMEOUT).json()
        if j.get("ok") != 1:
            raise RuntimeError(f"微博返回 ok={j.get('ok')}，Cookie 可能失效")
        for c in j["data"].get("cards", []):
            for g in c.get("card_group") or [c]:
                m = g.get("mblog")
                if not m:
                    continue
                posted = datetime.strptime(m["created_at"], "%a %b %d %H:%M:%S %z %Y").astimezone(timezone.utc)
                if posted < since:
                    continue
                out.append(Post("微博", f"https://m.weibo.cn/detail/{m['id']}", _clean(m.get("text")), posted,
                                m.get("user", {}).get("screen_name", ""), "", False))
    return out


def fetch_douyin(keywords, since):
    from browser import fetch_douyin as f
    return f(keywords, since, Post)


def fetch_xiaohongshu(keywords, since):
    from browser import fetch_xiaohongshu as f
    return f(keywords, since, Post)


SOURCES = {
    "bilibili": fetch_bilibili,        # 游客指纹 + WBI 签名
    "tieba": fetch_tieba,              # 贴吧客户端签名
    "douyin": fetch_douyin,            # 无头浏览器游客模式（页面自己算 a_bogus 签名）
    "xiaohongshu": fetch_xiaohongshu,  # 无头浏览器游客模式（页面自己算 X-s 签名）
    "weibo": fetch_weibo,              # 可选，需要 WEIBO_COOKIE
}
