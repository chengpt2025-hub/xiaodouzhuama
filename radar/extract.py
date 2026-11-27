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
    "WINDOW", "NEWWEB", "MOBILE", "BUTTON", "SEARCH", "NOTICE", "CHROME", "SAFARI", "SELECT", "SUBMIT",
    "ACCESS", "SERVER", "CLIENT", "DOMAIN", "CANCEL", "CREATE", "DELETE", "FOOTER", "HEADER", "IMAGES",
    "VIDEOS", "PUBLIC", "REPORT", "SOURCE", "STATUS", "TOKENS", "BROWSE", "ONLINE", "OFFLINE", "COOKIE",
    "000000", "111111", "666666", "888888", "AAAAAA", "HTTPS0", "UPDATE", "SYSTEM", "ONLINE",
}

CONTEXT_WORDS = ("小豆", "小荳", "豆包", "doubao", "邀请码", "邀請碼")


_UNIT = re.compile(r"^(?:\d+(?:[KMGT]B|PX|MS|HZ|FPS|MAH|MM|CM|KG|GHZ|MHZ|K|W|V)|(?:SAVE|OFF|VIP|GIFT|CODE|PLUS|PRO|MAX)\d+)$")


_YEARISH = re.compile(r"^[A-Z]{2}(19|20)\d\d$")  # BF2026、CT2020 这类“字母+年份”的活动码
_EXTRA_BLACK = {"LPDDR5", "LPDDR4", "GDDR6X", "PAN666", "WT588F", "ICLOUD", "HOTELS", "AIRBNB", "AMAZON", "TAOBAO", "LENOVO", "ALIPAY", "TMALL0"}


def _wordlike(c: str) -> bool:
    """纯字母且含 2 个以上元音，多半是英文单词或品牌名（LENOVO、SPEEDO、WILSON），不是随机生成的码。"""
    return c.isalpha() and sum(ch in "AEIOU" for ch in c) >= 2


def _valid(code: str, from_link: bool = False) -> bool:
    c = code.upper()
    if c in _EXTRA_BLACK or re.match(r"^(LP)?G?DDR\d", c):  # 内存规格之类
        return False
    if not from_link and (_YEARISH.match(c) or _wordlike(c)):
        return False
    if _UNIT.match(c):
        return False
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


# ------------------------------------------------------------ 时间识别 ----
_REL = [
    (re.compile(r"(\d+)\s*(?:小时|小時|h)\s*(\d+)\s*(?:分钟|分鐘|分|min)\S{0,2}前"), lambda m: timedelta(hours=int(m[1]), minutes=int(m[2]))),
    (re.compile(r"(\d+)\s*(?:秒|s)\S{0,2}前"), lambda m: timedelta(seconds=int(m[1]))),
    (re.compile(r"(\d+)\s*(?:分钟|分鐘|分)\S{0,2}前"), lambda m: timedelta(minutes=int(m[1]))),
    (re.compile(r"(\d+)\s*(?:小时|小時|个小时)\S{0,2}前"), lambda m: timedelta(hours=int(m[1]))),
    (re.compile(r"(\d+)\s*(?:天|日)前"), lambda m: timedelta(days=int(m[1]))),
    (re.compile(r"(\d+)\s*(?:seconds?|secs?)\s+ago", re.I), lambda m: timedelta(seconds=int(m[1]))),
    (re.compile(r"(\d+)\s*(?:minutes?|mins?)\s+ago", re.I), lambda m: timedelta(minutes=int(m[1]))),
    (re.compile(r"(\d+)\s*(?:hours?|hrs?)\s+ago", re.I), lambda m: timedelta(hours=int(m[1]))),
    (re.compile(r"(\d+)\s*days?\s+ago", re.I), lambda m: timedelta(days=int(m[1]))),
    (re.compile(r"刚刚|剛剛|just now", re.I), lambda m: timedelta(0)),
]
_ABS = re.compile(r"(?:(\d{4})[-/年.])?(\d{1,2})[-/月.](\d{1,2})日?\s+(\d{1,2})[:：](\d{2})")


def parse_post_time(text: str, now: datetime):
    """从“3NU8DZ … 1 小时 32 分钟前发出”“20 hours ago”“11-27 03:15”之类的文字里识别发帖时间。
    返回 (时间, 原文片段)；识别不到返回 (None, None)。会避开“有效期至 …”里的时间。"""
    if not text:
        return None, None
    clean = EXPIRE_RE.sub(" ", text)
    best = None
    for rx, fn in _REL:
        m = rx.search(clean)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), now - fn(m), m.group(0))
    m = _ABS.search(clean)
    if m and (best is None or m.start() < best[0]):
        y, mo, d, hh, mm = m.groups()
        try:
            dt = datetime(int(y) if y else now.astimezone(CST).year, int(mo), int(d), int(hh), int(mm), tzinfo=CST)
            if dt <= now + timedelta(minutes=5) and now - dt < timedelta(days=30):
                best = (m.start(), dt, m.group(0))
        except ValueError:
            pass
    if not best:
        return None, None
    return best[1].astimezone(timezone.utc), best[2]


_HEXISH = re.compile(r"^[A-F0-9]{6}$")
_CTX_NEAR = re.compile(r"小豆|小荳|邀请码|邀請碼|invite|豆包")


def extract_codes_strict(text: str):
    """用于搜索结果页 / 门户页：页面上杂讯多，只认“邀请码/小豆”附近 60 字以内的码，
    裸码还要求至少 2 个字母、且不能像十六进制数字（避免把 FIBA1993、颜色值等误认成码）。"""
    out = {}
    for code, conf in extract_codes(text, True):
        for m in re.finditer(code, text, re.I):
            win = text[max(0, m.start() - 60): m.end() + 60]
            if not _CTX_NEAR.search(win):
                continue
            letters = sum(ch.isalpha() for ch in code)
            if conf != "high" and (letters < 2 or _HEXISH.match(code)):
                continue
            # 纯字母的裸码（像 WINDOW、NEWWEB 这种英文单词）必须紧挨着“邀请码”才算
            if conf != "high" and code.isalpha() and not re.search(r"(邀请码|邀請碼|码|碼).{0,12}$", text[max(0, m.start() - 20): m.start()]):
                continue
            out[code] = conf
            break
    return list(out.items())


# 聚合站页面上的按钮文字，不能当成“已被用”的证据
_BUTTON_WORDS = re.compile(r"复制|已被用|待验证|标记|刷新")
_ORIGINS = [
    (re.compile(r"\bX\s*帖|x\.com|twitter|推特|\bX\b(?=\s*\d)", re.I), "X"),
    (re.compile(r"weibo|微博"), "微博"), (re.compile(r"小红书|xiaohongshu|xhs", re.I), "小红书"),
    (re.compile(r"抖音|douyin", re.I), "抖音"), (re.compile(r"bilibili|B站|b站"), "B站"),
    (re.compile(r"贴吧|tieba"), "百度贴吧"), (re.compile(r"linux\.do", re.I), "LINUX DO"),
    (re.compile(r"t\.me|telegram|电报", re.I), "Telegram"), (re.compile(r"即刻|jike", re.I), "即刻"),
    (re.compile(r"公众号|weixin", re.I), "微信公众号"), (re.compile(r"知乎|zhihu"), "知乎"),
    (re.compile(r"v2ex", re.I), "V2EX"), (re.compile(r"github", re.I), "GitHub"),
]


def origin_platform(seg: str):
    """聚合站列表里每个码后面通常写着它最初出自哪（如“X 帖”“weibo.com”），识别出来。"""
    for rx, name in _ORIGINS:
        if rx.search(seg or ""):
            return name
    return None


def looks_used_page(seg: str) -> bool:
    return looks_used(_BUTTON_WORDS.sub(" ", seg or ""))
