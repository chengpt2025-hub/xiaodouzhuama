"""全网免登录检索层：元搜索 + 网页阅读 + Telegram 公开频道 + GitHub。

用到的开源项目：
- ddgs（原 duckduckgo_search）：同时调用 Bing / Google / Yahoo / DuckDuckGo / Brave / Mojeek / Yandex 等搜索引擎，免 Key 免登录
- SearXNG：开源元搜索引擎，在 GitHub Actions 里用 Docker 临时起一个，聚合 70+ 搜索引擎
  （含百度、搜狗、搜狗微信、360、夸克等国内引擎）。设置了 SEARXNG_URL 才启用
- Jina Reader（r.jina.ai）：把任意网页（含需要 JS 渲染的）转成纯文本，免登录
- Telegram 网页预览 t.me/s/<频道>?q=关键词：公开频道免登录可搜
- GitHub 搜索 API：Actions 自带 GITHUB_TOKEN，可搜 Issue / 讨论
"""
import concurrent.futures as cf
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 15

WEB_KEYWORDS = [k.strip() for k in os.getenv(
    "RADAR_WEB_KEYWORDS",
    "小豆邀请码,小豆 邀请码 有效期至,小豆邀請碼,invite-share/M-,xiaodou invite code,豆包 小豆 邀请码 送",
).split(",") if k.strip()]

# 这些平台由专门的源处理（签名法 / 无头浏览器），网页阅读层跳过，避免重复和被封
SKIP_FETCH = ("bilibili.com", "b23.tv", "tieba.baidu.com", "douyin.com", "xiaohongshu.com", "xhslink.com",
              "weibo.com", "weibo.cn", "x.com", "twitter.com", "facebook.com", "instagram.com",
              "pan.quark.cn", "pan.baidu.com", "apps.apple.com", "xianyu", "goofish.com")
# 新闻 / 百科类大站：只看搜索摘要，不逐页读
NEWS_HOSTS = ("sina.com.cn", "sina.cn", "163.com", "qq.com", "sohu.com", "ifeng.com", "36kr.com",
              "thepaper.cn", "woshipm.com", "smzdm.com", "zhihu.com", "baike.baidu.com", "wikipedia.org")


def host_of(url):
    try:
        return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:  # noqa: BLE001
        return ""


# ------------------------------------------------------------ 元搜索 ----
def search_ddgs(keywords):
    from ddgs import DDGS
    backends = os.getenv("RADAR_DDGS_BACKENDS", "bing,google,yahoo,duckduckgo,brave,mojeek,yandex").split(",")
    results, errors = [], []
    for kw in keywords:
        for be in backends:
            try:
                rows = DDGS().text(kw, region="cn-zh", timelimit="d", max_results=20, backend=be.strip())
                for r in rows or []:
                    results.append({"url": r.get("href"), "title": r.get("title", ""), "snippet": r.get("body", ""),
                                    "engine": be.strip(), "published": None})
            except Exception as e:  # noqa: BLE001
                errors.append(f"{be}:{str(e)[:40]}")
            time.sleep(0.3)
    if not results:
        raise RuntimeError("所有搜索引擎都没有返回结果：" + "; ".join(errors[:6]))
    return results


def search_searxng(keywords):
    base = os.getenv("SEARXNG_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("未配置 SEARXNG_URL（Actions 里会自动启动一个），本地运行时跳过")
    results = []
    for kw in keywords:
        for cat in ("general", "news", "social media"):
            try:
                j = requests.get(f"{base}/search", params={"q": kw, "format": "json", "time_range": "day",
                                                            "categories": cat, "language": "all"},
                                 timeout=40).json()
            except Exception as e:  # noqa: BLE001
                print(f"  [SearXNG] {kw}/{cat} 失败: {e}")
                continue
            for r in j.get("results") or []:
                results.append({"url": r.get("url"), "title": r.get("title", ""), "snippet": r.get("content", ""),
                                "engine": ",".join(r.get("engines") or []), "published": r.get("publishedDate")})
    if not results:
        raise RuntimeError("SearXNG 没有返回结果")
    return results


# ---------------------------------------------------------- 网页阅读 ----
def read_page(url):
    """先直接请求；内容太少（JS 渲染页）或被拦时，改用 Jina Reader 渲染成纯文本。"""
    text = ""
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}, timeout=TIMEOUT)
        if r.ok and "text/html" in r.headers.get("content-type", "") or r.ok and "json" in r.headers.get("content-type", ""):
            r.encoding = r.apparent_encoding or r.encoding
            h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", r.text)
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))
    except Exception:  # noqa: BLE001
        pass
    if len(text) < 400:
        try:
            r = requests.get("https://r.jina.ai/" + url, headers={"User-Agent": UA, "X-Return-Format": "text"},
                             timeout=30)
            if r.ok:
                text = r.text
        except Exception:  # noqa: BLE001
            pass
    return text[:200000]


# ---------------------------------------------------------- Telegram ----
TG_RE = re.compile(r"(?:https?://)?t\.me/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})(?:[/?]|$)")


def telegram_posts(channels, since, Post):
    out = []
    for ch in channels:
        try:
            r = requests.get(f"https://t.me/s/{ch}", params={"q": "小豆"}, headers={"User-Agent": UA}, timeout=TIMEOUT)
        except Exception:  # noqa: BLE001
            continue
        for blk in re.findall(r'<div class="tgme_widget_message_wrap.*?</time>', r.text, re.S):
            link = re.search(r'data-post="([^"]+)"', blk)
            tm = re.search(r'<time[^>]*datetime="([^"]+)"', blk)
            body = re.search(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', blk, re.S)
            if not (link and tm and body):
                continue
            t = datetime.fromisoformat(tm.group(1).replace("Z", "+00:00")).astimezone(timezone.utc)
            if t < since:
                continue
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body.group(1)))
            out.append(Post("Telegram", f"https://t.me/{link.group(1)}", txt, t, ch, "", False))
    return out


# ------------------------------------------------------------ GitHub ----
def github_posts(since, Post):
    tok = os.getenv("GITHUB_TOKEN", "")
    h = {"Accept": "application/vnd.github+json", "User-Agent": "xiaodou-radar"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    out = []
    day = (since - timedelta(hours=1)).strftime("%Y-%m-%d")
    for q in ("小豆 邀请码", "xiaodou invite"):
        try:
            j = requests.get("https://api.github.com/search/issues",
                             params={"q": f"{q} updated:>={day}", "sort": "updated", "per_page": 30},
                             headers=h, timeout=TIMEOUT).json()
        except Exception:  # noqa: BLE001
            continue
        for it in j.get("items") or []:
            t = datetime.fromisoformat(it["created_at"].replace("Z", "+00:00"))
            out.append(Post("GitHub", it["html_url"], f"{it.get('title', '')} {it.get('body') or ''}",
                            t, (it.get("user") or {}).get("login", ""), it.get("title", ""), False))
    return out


# ------------------------------------------------------------ 汇总 ----
def fetch_web(keywords, since, Post):
    """把元搜索结果变成 Post：摘要本身算一条，再并发读取正文页。"""
    kws = list(dict.fromkeys(WEB_KEYWORDS + list(keywords)))
    results, notes = [], []
    for name, fn in (("ddgs", search_ddgs), ("searxng", search_searxng)):
        try:
            got = fn(kws)
            results += got
            notes.append(f"{name}:{len(got)}")
        except Exception as e:  # noqa: BLE001
            notes.append(f"{name}:失败")
            print(f"  [全网] {name} 不可用: {e}")
    if not results:
        raise RuntimeError("元搜索全部失败")
    now = datetime.now(timezone.utc)
    by_url = {}
    for r in results:
        u = (r.get("url") or "").split("#")[0]
        if u.startswith("http") and u not in by_url:
            by_url[u] = r
    out, tg = [], set(os.getenv("RADAR_TG_CHANNELS", "").split(",")) - {""}
    for u, r in by_url.items():
        pub = None
        if r.get("published"):
            try:
                pub = datetime.fromisoformat(str(r["published"]).replace("Z", "+00:00"))
                pub = pub if pub.tzinfo else pub.replace(tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                pub = None
        p = Post("全网·" + host_of(u), u, f"{r.get('title', '')} {r.get('snippet', '')}", pub or now,
                 r.get("engine", ""), r.get("title", ""), False)
        p.time_estimated = pub is None
        out.append(p)
        for m in TG_RE.finditer(u + " " + (r.get("snippet") or "")):
            tg.add(m.group(1))
    # 并发读取正文
    max_pages = int(os.getenv("RADAR_WEB_PAGES", "40"))
    targets = [u for u in by_url if not any(s in host_of(u) for s in SKIP_FETCH + NEWS_HOSTS)][:max_pages]
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for u, text in zip(targets, ex.map(read_page, targets)):
            if not text:
                continue
            for m in TG_RE.finditer(text):
                tg.add(m.group(1))
            p = Post("全网·" + host_of(u), u, text, now, "", by_url[u].get("title", ""), True)
            p.time_estimated = True
            p.page_text = True
            out.append(p)
    tg = {c for c in tg if c.lower() not in ("share", "joinchat", "addstickers", "proxy", "iv", "s")}
    out += telegram_posts(list(tg)[:int(os.getenv("RADAR_TG_MAX", "25"))], since, Post)
    out += github_posts(since, Post)
    print(f"  [全网] 搜索结果 {len(by_url)} 个网址（{', '.join(notes)}），读正文 {len(targets)} 页，Telegram 频道 {len(tg)} 个")
    return out
