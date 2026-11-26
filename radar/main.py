"""小豆邀请码社交雷达：抓取 -> 提取 -> 合并历史 -> 输出 codes.json"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from extract import extract_codes, has_context, looks_for_sale, looks_used, parse_expire, parse_post_time  # noqa: E402
from sources import SOURCES  # noqa: E402

KEYWORDS = [k.strip() for k in os.getenv("RADAR_KEYWORDS", "小豆邀请码,小豆 邀请码,小豆邀请").split(",") if k.strip()]
LOOKBACK_HOURS = float(os.getenv("RADAR_LOOKBACK_HOURS", "48"))
KEEP_HOURS = float(os.getenv("RADAR_KEEP_HOURS", "72"))


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {"codes": []}


def run(out_path, prev_path):
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=LOOKBACK_HOURS)
    prev = {c["code"]: c for c in load(prev_path).get("codes", [])}
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
        found = extract_codes(p.text, ctx)
        is_page = getattr(p, "page_text", False) or getattr(p, "time_estimated", False)
        aggregator = getattr(p, "page_text", False) and len(found) >= 5  # 一页里一堆码 = 抓码 / 聚合站
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
                        "snippet": (seg if getattr(p, "page_text", False) else p.text)[:160],
                        "title": p.title[:80], "confidence": conf,
                        "expires_at": iso(exp) if exp else None, "suspect_used": used,
                        "suspect_sale": looks_for_sale(seg), "aggregator": aggregator,
                        "invite_link": f"https://activity.doubao.com/ug/invite-share/M-{code}",
                        "seen_count": 1, "seen_on": [p.source]}
                codes[code] = item
            else:
                item.setdefault("time_source", "首次发现" if item.get("time_estimated") else "原帖时间")
                if p.source not in item.setdefault("seen_on", [item["source"]]):
                    item["seen_on"].append(p.source)
                    item["seen_count"] = len(item["seen_on"])
                better = RANK[tsrc] > RANK.get(item["time_source"], 1)
                earlier = (RANK[tsrc] == RANK.get(item["time_source"], 1) and posted and item.get("posted_at")
                           and posted < datetime.fromisoformat(item["posted_at"].replace("Z", "+00:00")))
                if posted and (better or earlier):
                    item.update(posted_at=iso(posted), time_source=tsrc, time_text=raw, source=p.source,
                                url=p.url, author=p.author, aggregator=aggregator,
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

    data = {"updated_at": iso(now), "keywords": KEYWORDS, "sources": status,
            "count": len(result), "codes": result}
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"共 {len(result)} 个码，已写入 {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data/codes.json")
    ap.add_argument("--prev", default="site/data/codes.json")
    ap.add_argument("--loops", type=int, default=int(os.getenv("RADAR_LOOPS", "1")))
    ap.add_argument("--interval", type=int, default=int(os.getenv("RADAR_INTERVAL", "60")))
    a = ap.parse_args()
    for i in range(a.loops):
        run(a.out, a.prev if i == 0 else a.out)
        if i < a.loops - 1:
            time.sleep(a.interval)
