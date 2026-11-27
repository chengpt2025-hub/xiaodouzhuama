"""小豆邀请码社交雷达：抓取 -> 提取 -> 合并历史 -> 输出 codes.json"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from extract import extract_codes, extract_codes_strict, has_context, looks_for_sale, looks_used, parse_expire, parse_post_time  # noqa: E402
from sources import SOURCES  # noqa: E402

KEYWORDS = [k.strip() for k in os.getenv("RADAR_KEYWORDS", "小豆邀请码,小豆 邀请码,小豆邀请").split(",") if k.strip()]
LOOKBACK_HOURS = float(os.getenv("RADAR_LOOKBACK_HOURS", "48"))
KEEP_HOURS = float(os.getenv("RADAR_KEEP_HOURS", "72"))


PLATFORM_HOSTS = [
    ("bilibili.com", "B站"), ("b23.tv", "B站"), ("tieba.baidu.com", "百度贴吧"), ("douyin.com", "抖音"),
    ("xiaohongshu.com", "小红书"), ("xhslink.com", "小红书"), ("weibo.com", "微博"), ("weibo.cn", "微博"),
    ("x.com", "X"), ("twitter.com", "X"), ("t.me", "Telegram"), ("github.com", "GitHub"),
    ("zhihu.com", "知乎"), ("linux.do", "LINUX DO"), ("v2ex.com", "V2EX"), ("reddit.com", "Reddit"),
    ("threads.net", "Threads"), ("facebook.com", "Facebook"), ("youtube.com", "YouTube"),
    ("kuaishou.com", "快手"), ("douban.com", "豆瓣"), ("csdn.net", "CSDN"), ("juejin.cn", "掘金"),
    ("weixin.qq.com", "微信公众号"), ("smzdm.com", "什么值得买"), ("xianyu", "闲鱼"), ("goofish.com", "闲鱼"),
]


def platform_of(source, url, aggregator):
    """只保留平台名，不保留具体出处。"""
    if aggregator:
        return "抓码聚合站"
    if source.startswith("门户·"):
        return source.split("·", 1)[1]
    import urllib.parse as _up
    try:
        host = _up.urlparse(url or "").netloc.lower().split(":")[0]
    except Exception:  # noqa: BLE001
        host = ""
    for h, name in PLATFORM_HOSTS:
        if host == h or host.endswith("." + h) or ("." not in h and h in host):
            return name
    base = source.split("·")[0].replace("评论", "").replace("楼层", "")
    return {"全网": "其他网页", "贴吧": "百度贴吧"}.get(base, base)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {"codes": []}


def run(out_path, prev_path, state_path):
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=LOOKBACK_HOURS)
    prev = {c["code"]: c for c in load(prev_path).get("codes", [])}  # prev_path 是内部状态文件
    status = {}
    posts = []
    enabled = [s for s in os.getenv("RADAR_SOURCES", ",".join(SOURCES)).split(",") if s in SOURCES]
    for name in enabled:
        t0 = time.time()
        try:
            got = SOURCES[name](KEYWORDS, since)
            posts.extend(got)
            status[name] = {"ok": True, "posts": len(got), "seconds": round(time.time() - t0, 1)}
            print(f"[{name}] OK，{len(got)} 条")
        except Exception as e:  # noqa: BLE001
            status[name] = {"ok": False, "error": str(e)[:200]}
            print(f"[{name}] 失败：{e}")

    codes = dict(prev)
    RANK = {"原帖时间": 3, "页面标注": 2, "首次发现": 1}
    for p in posts:
        ctx = p.is_topic or has_context(p.title) or has_context(p.text)
        found = extract_codes_strict(p.text) if getattr(p, "serp", False) else extract_codes(p.text, ctx)
        is_page = getattr(p, "page_text", False) or getattr(p, "time_estimated", False)
        aggregator = getattr(p, "page_text", False) and not getattr(p, "serp", False) and len(found) >= 5  # 一页里一堆码 = 抓码 / 聚合站
        up = p.text.upper()
        pos = sorted((up.find(c), c) for c, _ in found if up.find(c) >= 0)
        for code, conf in found:
            i = up.find(code)
            # 这个码自己的那一段：从码开始，到下一个码之前（聚合站列表里每个码一段）
            nxt = [j for j, _ in pos if j > i]
            seg = p.text[i: (nxt[0] if nxt else i + 200)][:200] if i >= 0 else p.text[:200]
            near = (p.text[max(0, i - 80): i] + seg) if i >= 0 else p.text[:240]
            exp = parse_expire(seg, p.posted_at) or parse_expire(near, p.posted_at)
            if is_page:
                t, raw = parse_post_time(seg, now)
                if t is None and not getattr(p, "page_text", False):  # 搜索摘要：整段找
                    t, raw = parse_post_time(p.text, now)
                tsrc, posted = ("页面标注", t) if t else ("首次发现", None)
            else:
                tsrc, posted, raw = "原帖时间", p.posted_at, None
            used = any(looks_used(r) for r in p.replies) or (getattr(p, "page_text", False) and looks_used(seg))
            item = codes.get(code)
            if item is None:
                item = {"code": code, "first_seen": iso(now),
                        "posted_at": iso(posted) if posted else None, "time_source": tsrc, "time_text": raw,
                        "source": p.source, "url": p.url, "author": p.author,
                        "platform": platform_of(p.source, p.url, aggregator),
                        "snippet": (seg if getattr(p, "page_text", False) else p.text)[:160],
                        "title": p.title[:80], "confidence": conf,
                        "expires_at": iso(exp) if exp else None, "suspect_used": used,
                        "suspect_sale": looks_for_sale(seg), "aggregator": aggregator,
                        "invite_link": f"https://activity.doubao.com/ug/invite-share/M-{code}",
                        "seen_count": 1, "last_seen": iso(now)}
                item["seen_on"] = [item["platform"]]
                codes[code] = item
            else:
                item.setdefault("time_source", "首次发现" if item.get("time_estimated") else "原帖时间")
                plat = platform_of(p.source, p.url, aggregator)
                if plat not in item.setdefault("seen_on", [item.get("platform", plat)]):
                    item["seen_on"].append(plat)
                    item["seen_count"] = len(item["seen_on"])
                item["last_seen"] = iso(now)
                better = RANK[tsrc] > RANK.get(item["time_source"], 1)
                earlier = (RANK[tsrc] == RANK.get(item["time_source"], 1) and posted and item.get("posted_at")
                           and posted < datetime.fromisoformat(item["posted_at"].replace("Z", "+00:00")))
                if posted and (better or earlier):
                    item.update(posted_at=iso(posted), time_source=tsrc, time_text=raw, source=p.source,
                                url=p.url, author=p.author, aggregator=aggregator,
                                platform=platform_of(p.source, p.url, aggregator),
                                snippet=(seg if getattr(p, "page_text", False) else p.text)[:160])
                if exp and not item.get("expires_at"):
                    item["expires_at"] = iso(exp)
                if conf == "high":
                    item["confidence"] = "high"
                item["suspect_used"] = item.get("suspect_used") or used
            item.pop("time_estimated", None)

    keep_after = now - timedelta(hours=KEEP_HOURS)
    result = []
    for c in codes.values():
        posted = datetime.fromisoformat((c.get("posted_at") or c["first_seen"]).replace("Z", "+00:00"))
        exp = c.get("expires_at")
        if exp and datetime.fromisoformat(exp.replace("Z", "+00:00")) < now - timedelta(hours=1):
            continue
        if posted < keep_after:
            continue
        result.append(c)
    result.sort(key=lambda c: c.get("posted_at") or c["first_seen"], reverse=True)

    # 内部状态（含出处，用于下一轮合并）与公开数据（不含出处）分开保存
    state = {"updated_at": iso(now), "codes": result, "scans": (load(prev_path).get("scans") or [])[-95:]}
    new_codes = [c for c in result if c["code"] not in prev]
    state["scans"].append({"at": iso(now), "new": len(new_codes), "total": len(result),
                           "sources": {k: (v.get("posts", 0) if v.get("ok") else -1) for k, v in status.items()}})
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    KEEP = ("code", "platform", "seen_on", "seen_count", "first_seen", "last_seen", "posted_at", "time_source",
            "time_text", "expires_at", "confidence", "suspect_used", "suspect_sale", "aggregator", "invite_link")
    public = [{k: c.get(k) for k in KEEP} for c in result]
    for c in public:
        c.setdefault("platform", None)
        if not c["platform"]:
            c["platform"] = "其他网页"
    since24 = now - timedelta(hours=24)
    data = {"updated_at": iso(now), "count": len(public), "codes": public,
            "sources": {k: {"ok": v.get("ok"), "posts": v.get("posts", 0)} for k, v in status.items()},
            "stats": {"new_this_scan": len(new_codes),
                      "found_24h": sum(1 for c in result if c["first_seen"] >= iso(since24)),
                      "scans": state["scans"][-48:]}}
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(os.path.join(os.path.dirname(out_path) or ".", "diag.json"), "w", encoding="utf-8") as f:
        json.dump({"at": iso(now), "sources": status}, f, ensure_ascii=False, indent=1)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"共 {len(result)} 个码，已写入 {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data/codes.json")
    ap.add_argument("--state", default="state/state.json", help="内部状态（含出处），不发布到网页")
    ap.add_argument("--loops", type=int, default=int(os.getenv("RADAR_LOOPS", "1")))
    ap.add_argument("--interval", type=int, default=int(os.getenv("RADAR_INTERVAL", "60")))
    a = ap.parse_args()
    for i in range(a.loops):
        os.makedirs(os.path.dirname(a.state) or ".", exist_ok=True)
        run(a.out, a.state, a.state)
        if i < a.loops - 1:
            time.sleep(a.interval)
