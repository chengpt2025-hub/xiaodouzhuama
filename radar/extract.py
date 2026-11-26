"""从帖子/评论文本里提取小豆邀请码、有效期，并判断是否疑似已被领走。"""
import re
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))

# 官方分享链接里的码，最可靠
LINK_RE = re.compile(r"invite-share/M-([A-Za-z0-9]{6})(?![A-Za-z0-9])")
# “邀请码：XXXXXX” / “邀请码 XXXXXX” / “码：XXXXXX”
LABEL_RE = re.compile(r"(?:邀请码|邀請碼|码|碼)\s*(?:是|为|:|：|\s)\s*([A-Za-z0-9]{6})(?![A-Za-z0-9])")
# 上下文已经明确在聊小豆邀请码时，独立出现的 6 位大写字母数字
BARE_RE = re.compile(r"(?<![A-Za-z0-9/._\-=@#])([A-Z0-9]{6})(?![A-Za-z0-9/._\-])")

EXPIRE_RE = re.compile(
    r"有效期(?:至|到)?\s*[:：]?\s*(?:(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})日?|(\d{1,2})月(\d{1,2})日)\s*(\d{1,2})[:：](\d{2})"
)

USED_WORDS = ("已用", "用了", "被用", "已被使用", "没了", "沒了", "领完", "領完", "抢完", "搶完",
              "失效", "无效", "無效", "过期", "過期", "已领", "已領", "手慢")
SALE_WORDS = ("出售", "元一个", "元/个", "块一个", "收费", "付费", "押金", "闲鱼", "私信", "加群", "进群", "加v", "加V", "vx", "VX", "wzyp.cn/shop")

BLACKLIST = {
    "DOUBAO", "XIAODO", "GEMINI", "OPENAI", "GITHUB", "IPHONE", "WECHAT", "BILIBI", "ANDROI",
    "INVITE", "SHARE0", "CHATGP", "GOOGLE", "TIKTOK", "DOUYIN", "WEIBO0", "QQ1234", "123456",
    "000000", "111111", "666666", "888888", "AAAAAA", "HTTPS0", "UPDATE", "SYSTEM", "ONLINE",
}

CONTEXT_WORDS = ("小豆", "小荳", "豆包", "doubao", "邀请码", "邀請碼")


def _valid(code: str) -> bool:
    c = code.upper()
    if c in BLACKLIST:
        return False
    if c.isdigit():  # 纯数字多半是时间/金额/QQ号，官方码目前都带字母
        return False
    if c.isalpha() and c.lower() == c:  # 纯小写单词
        return False
    if len(set(c)) <= 2:
        return False
    return True


def parse_expire(text: str, ref: datetime):
    m = EXPIRE_RE.search(text)
    if not m:
        return None
    y, mo, d, mo2, d2, hh, mm = m.groups()
    try:
        if y:
            dt = datetime(int(y), int(mo), int(d), int(hh), int(mm), tzinfo=CST)
        else:
            dt = datetime(ref.astimezone(CST).year, int(mo2), int(d2), int(hh), int(mm), tzinfo=CST)
            if dt < ref - timedelta(days=200):  # 跨年
                dt = dt.replace(year=dt.year + 1)
        return dt
    except ValueError:
        return None


def has_context(text: str) -> bool:
    low = text.lower()
    return any(w.lower() in low for w in CONTEXT_WORDS)


def extract_codes(text: str, context_ok: bool = False):
    """返回 [(CODE, 置信度)]。context_ok=True 表示所属帖子本身就是小豆邀请码主题。"""
    if not text:
        return []
    found = {}
    for m in LINK_RE.finditer(text):
        found[m.group(1).upper()] = "high"
    ctx = context_ok or has_context(text)
    if ctx:
        for m in LABEL_RE.finditer(text):
            c = m.group(1).upper()
            if _valid(c):
                found.setdefault(c, "high")
        for m in BARE_RE.finditer(text):
            c = m.group(1)
            if _valid(c) and any(ch.isalpha() for ch in c) and any(ch.isdigit() for ch in c) or (
                _valid(c) and c.isalpha() and ("邀请码" in text or "码" in text) and len(text) < 300
            ):
                found.setdefault(c, "medium")
    return list(found.items())


def looks_used(text: str) -> bool:
    return any(w in text for w in USED_WORDS)


def looks_for_sale(text: str) -> bool:
    return any(w in text for w in SALE_WORDS)
