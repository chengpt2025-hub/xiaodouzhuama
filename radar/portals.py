"""国内外门户 / 第三方入口：不从平台官方搜索进，改从其他能免登录搜索的入口进。

实测（2026-11-27）可免登录直接搜索的入口：
- 今日头条搜索（综合 / 微头条）：同属字节，能搜到微头条、头条号文章和抖音视频，带“X 小时前”时间
- 夸克搜索、360 搜索：国内搜索引擎，收录小红书 / 知乎 / 微博 / 公众号内容
- 搜狗知乎频道：知乎回答和文章
- 豆瓣搜索、虎扑搜索、SOV2EX（V2EX 第三方搜索 API，带发帖时间）
用 curl_cffi 模拟 Chrome 浏览器指纹访问。头条结果里出现的抖音作品 ID 会交给抖音源抓评论。
"""
import html as H
import os
import re
import time
import urllib.parse as up
from datetime import datetime, timezone

from curl_cffi import requests as cr

from extract import extract_codes_strict
from shared import DISCOVERED

PORTALS = [
    ("今日头条", "https://so.toutiao.com/search?keyword={q}&pd=synthesis&dvpf=pc&filter_vendor=site&index_resource=site&filter_period=day"),
    ("今日头条", "https://so.toutiao.com/search?keyword={q}&pd=weitoutiao&dvpf=pc"),
    ("今日头条", "https://so.toutiao.com/search?keyword={q}&pd=video&dvpf=pc"),
    ("夸克搜索", "https://quark.sm.cn/s?q={q}"),
    ("360搜索", "https://www.so.com/s?q={q}&adv_t=d"),
    ("知乎", "https://www.sogou.com/sogou?query={q}&insite=zhihu.com"),
    ("豆瓣", "https://www.douban.com/search?q={q}"),
    ("虎扑", "https://bbs.hupu.com/search?q={q}&sortby=time"),
]


def _unescape(t):
    t = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), t)
    return H.unescape(t).replace("\\/", "/")


def _visible(t):
    t = re.sub(r"(?is)<(style|noscript)[^>]*>.*?</\1>", " ", t)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))


def fetch_portals(keywords, since, Post):
    s = cr.Session(impersonate="chrome")
    out, ok, errs = [], 0, []
    now = datetime.now(timezone.utc)
    for kw in keywords[:2]:
        q = up.quote(kw)
        for name, tpl in PORTALS:
            try:
                r = s.get(tpl.format(q=q), timeout=20)
                if r.status_code != 200 or "captcha" in str(r.url):
                    errs.append(f"{name}:{r.status_code}")
                    continue
                raw = _unescape(r.text)
            except Exception as e:  # noqa: BLE001
                errs.append(f"{name}:{str(e)[:30]}")
                continue
            ok += 1
            for m in re.finditer(r"(?:douyin\.com/(?:video|note)/|aweme_id[\"=:]+\"?|\"group_id\":\"?)(\d{17,21})", raw):
                DISCOVERED["douyin"].add(m.group(1))
            for m in re.finditer(r"xiaohongshu\.com/(?:explore|discovery/item)/([0-9a-f]{24})(?:\?[^\"' <]*)?", raw):
                DISCOVERED["xiaohongshu"].add(m.group(0))
            text = _visible(raw)
            if extract_codes_strict(text):
                p = Post("门户·" + name, r.url, text, now, "", kw, True)
                p.time_estimated = True
                p.page_text = True
                p.serp = True
                out.append(p)
            time.sleep(0.4)
    # SOV2EX：V2EX 第三方搜索，带精确发帖时间
    try:
        j = s.get("https://www.sov2ex.com/api/search", params={"q": keywords[0], "sort": "created", "size": 30},
                  timeout=20).json()
        ok += 1
        for h in j.get("hits") or []:
            src = h.get("_source") or {}
            t = datetime.fromisoformat(str(src.get("created", "")).replace("Z", "+00:00")) if src.get("created") else None
            if t and t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if t and t >= since:
                out.append(Post("V2EX", f"https://www.v2ex.com/t/{src.get('id')}",
                                f"{src.get('title', '')} {src.get('content', '')}", t, "", src.get("title", ""), False))
    except Exception as e:  # noqa: BLE001
        errs.append(f"sov2ex:{str(e)[:30]}")
    print(f"  [门户] 成功 {ok} 个入口；发现抖音作品 {len(DISCOVERED['douyin'])} 个、小红书笔记 {len(DISCOVERED['xiaohongshu'])} 篇；失败 {errs}")
    if ok == 0:
        raise RuntimeError("所有门户入口都失败：" + "; ".join(errs[:5]))
    return out
