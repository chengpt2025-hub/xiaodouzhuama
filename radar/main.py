"""小豆邀请码社交雷达：抓取 -> 提取 -> 合并历史 -> 输出 codes.json"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from extract import extract_codes, has_context, looks_for_sale, looks_used, parse_expire  # noqa: E402
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
    for p in posts:
        ctx = p.is_topic or has_context(p.title) or has_context(p.text)
        for code, conf in extract_codes(p.text, ctx):
            exp = parse_expire(p.text, p.posted_at)
            used = any(code in r or looks_used(r) for r in p.replies if looks_used(r))
            item = codes.get(code)
            if item is None:
                item = {"code": code, "first_seen": iso(now), "posted_at": iso(p.posted_at),
                        "source": p.source, "url": p.url, "author": p.author,
                        "snippet": p.text[:160], "title": p.title[:80], "confidence": conf,
                        "expires_at": iso(exp) if exp else None, "suspect_used": used,
                        "suspect_sale": looks_for_sale(p.text),
                        "invite_link": f"https://activity.doubao.com/ug/invite-share/M-{code}",
                        "seen_count": 1}
                codes[code] = item
            else:
                item["seen_count"] = item.get("seen_count", 1) + (1 if p.url != item["url"] else 0)
                if p.posted_at < datetime.fromisoformat(item["posted_at"].replace("Z", "+00:00")):
                    item.update(posted_at=iso(p.posted_at), source=p.source, url=p.url, author=p.author)
                if exp and not item.get("expires_at"):
                    item["expires_at"] = iso(exp)
                if conf == "high":
                    item["confidence"] = "high"
                item["suspect_used"] = item.get("suspect_used") or used

    keep_after = now - timedelta(hours=KEEP_HOURS)
    result = []
    for c in codes.values():
        posted = datetime.fromisoformat(c["posted_at"].replace("Z", "+00:00"))
        exp = c.get("expires_at")
        if exp and datetime.fromisoformat(exp.replace("Z", "+00:00")) < now - timedelta(hours=1):
            continue
        if posted < keep_after:
            continue
        result.append(c)
    result.sort(key=lambda c: c["posted_at"], reverse=True)

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
