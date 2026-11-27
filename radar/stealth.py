"""Scrapling 隐身浏览器入口（D4Vinci/Scrapling，BSD-3）。

用 StealthyFetcher（指纹伪装 + 自动过 Cloudflare Turnstile / 5 秒盾）去开那些普通请求被拦的站：
linux.do、X 镜像、Reddit、搜狗微信、百度等。它解决的是“反爬拦截”，解决不了“必须登录才能搜”
（抖音 / 小红书 / 微博的搜索接口是服务端强制登录，换什么浏览器都一样）。
首次运行时在 GitHub Actions 上自动安装，失败不影响其它源。
"""
import re
import subprocess
import sys
import time
import urllib.parse as up
from datetime import datetime, timezone

from extract import extract_codes_strict, origin_platform

TARGETS = [
    ("LINUX DO", "https://linux.do/search?q={q}%20order%3Alatest"),
    ("X", "https://xcancel.com/search?f=tweets&q={q}"),
    ("X", "https://nitter.net/search?f=tweets&q={q}"),
    ("Reddit", "https://www.reddit.com/search/?q={q}&sort=new"),
    ("微信公众号", "https://weixin.sogou.com/weixin?type=2&query={q}"),
    ("百度", "https://www.baidu.com/s?wd={q}&gpc=stf"),
    ("必应", "https://cn.bing.com/search?q={q}&filters=ex1%3a%22ez1%22"),
    ("快手", "https://www.kuaishou.com/search/video?searchKey={q}"),
]
_READY = None


def _ensure():
    global _READY
    if _READY is not None:
        return _READY
    try:
        from scrapling.fetchers import StealthyFetcher  # noqa: F401
    except Exception:  # noqa: BLE001
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "scrapling[fetchers]"], timeout=300, check=False)
    try:
        subprocess.run(["scrapling", "install"], timeout=420, check=False)
        # 兜底：scrapling 底层用 patchright，单独把它的 chromium 也装上
        subprocess.run([sys.executable, "-m", "patchright", "install", "chromium"], timeout=300, check=False)
        from scrapling.fetchers import StealthyFetcher  # noqa: F401,F811
        _READY = True
    except Exception as e:  # noqa: BLE001
        print("  [scrapling] 安装失败:", e)
        _READY = False
    return _READY


def _chrome_path():
    """工作流里已经装好的 Playwright Chromium，作为 Scrapling 浏览器启动失败时的备用可执行文件。"""
    import glob
    import os
    for pat in ("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome",
                "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-*/headless_shell"):
        hits = sorted(glob.glob(os.path.expanduser(pat)))
        if hits:
            return hits[-1]
    return None


def _fetch(url):
    from scrapling.fetchers import StealthyFetcher
    kw = dict(headless=True, solve_cloudflare=True, network_idle=True, timeout=45000)
    try:
        return StealthyFetcher.fetch(url, **kw)
    except Exception as e:  # noqa: BLE001
        exe = _chrome_path()
        if exe and "launch" in str(e):
            return StealthyFetcher.fetch(url, executable_path=exe, **kw)
        raise


def _text(page):
    raw = getattr(page, "html_content", None) or str(getattr(page, "body", "") or "")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "ignore")
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))


def fetch_stealth(keywords, since, Post):
    if not _ensure():
        raise RuntimeError("Scrapling 没装上，本轮跳过")
    out, ok, errs = [], [], []
    now = datetime.now(timezone.utc)
    q = up.quote(keywords[0])
    for name, tpl in TARGETS:
        url = tpl.format(q=q)
        try:
            page = _fetch(url)
            status = getattr(page, "status", 0)
            text = _text(page)
            if status >= 400 or len(text) < 200 or re.search(r"安全验证|验证码|captcha|Just a moment|请先登录", text[:3000], re.I):
                errs.append(f"{name}:{status}/{len(text)}")
                continue
            ok.append(name)
            for code, conf in extract_codes_strict(text):
                i = text.upper().find(code)
                seg = text[max(0, i - 150): i + 150]
                p = Post(origin_platform(seg) or name, url, seg, now, "", keywords[0], True)
                p.time_estimated = True
                p.page_text = True
                p.serp = True
                out.append(p)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name}:{str(e).splitlines()[0][:40]} {str(e)[-80:]}")
        time.sleep(0.5)
    print(f"  [scrapling] 通了 {ok}；没通 {errs}")
    if not ok:
        raise RuntimeError("Scrapling 入口全部失败：" + "; ".join(errs[:6]))
    return out
