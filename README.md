# 小豆邀请码 · 全网社交雷达（xiaodouzhuama）

自动在**社交 / 娱乐平台的公开帖子和评论**里蹲「小豆」（豆包旗下 AI 个人助理，字节跳动）的公测邀请码，筛出 **10 分钟内刚发出的鲜码**，用一个 iOS 风格的网页实时展示。

- 不抓“抓码网站”，只抓平台上真人发的帖子和评论
- 全程**免登录**：用平台网页端自带的游客机制（游客指纹 + 公开签名算法），不需要你的任何账号
- 云端运行：GitHub Actions 每 5 分钟扫一次，GitHub Pages 托管网页，零服务器成本
- 以后要迁到自己服务器，整个仓库拷过去加一条 `crontab` 就行（见下文）

> 本项目只读取公开内容，不登录、不发帖、不评论、不代领、不倒卖。码能不能用以小豆 App 验证为准，**请勿付费买码**，更不要交押金。

---

## 网页长什么样

- 顶部：雷达上次扫描时间、码的总数、各平台抓取状态（正常 / 暂不可用）
- 开关：「只看 10 分钟内鲜码」「隐藏疑似已领 / 售卖」、按平台筛选
- 每张卡片：邀请码（大字号）、一键复制、直接打开官方邀请链接 `activity.doubao.com/ug/invite-share/M-XXXXXX`、可信度、有效期、原帖链接、发布于几分钟前
- 10 分钟内的鲜码会用绿色描边高亮；页面每 30 秒自动拉一次新数据
- 自动跟随系统深色 / 浅色模式

## 目前接入的平台

| 平台 | 状态 | 抓什么 | 说明 |
|---|---|---|---|
| B 站 | 免登录，已实测可用 | 按“最新发布”搜视频和专栏，再按时间抓每条的评论和楼中楼 | 游客 buvid + WBI 签名，和网页端算法一致 |
| 百度贴吧 | 免登录，尝试中 | 按时间排序的全吧搜索 | 部分 IP 会被安全验证拦截，被拦时自动跳过本轮 |
| 微博 | 可选 | 实时搜索 | 微博搜索现在强制登录，**默认关闭**；想开的话在仓库 Secret 里加 `WEIBO_COOKIE` |

暂未接入（如实说明）：

- **X（推特）**：搜索接口已经全部要求登录，公开镜像站基本失效
- **小红书**：搜索需要登录 + 签名，游客拿不到搜索结果
- **抖音**：综合搜索需要登录态和 a_bogus 签名；可以用之前抖音项目里那套游客凭证 + 无头浏览器的方法做，但比较重，放到下一版

新增平台很简单：在 `radar/sources.py` 里写一个 `fetch_xxx(keywords, since)` 函数，返回 `Post` 列表，然后加进 `SOURCES` 字典即可。

## 怎么识别邀请码

`radar/extract.py`：

1. **官方分享链接**里的码（`invite-share/M-XXXXXX`）→ 高可信
2. 「邀请码：XXXXXX」这种明确标注的 6 位字母数字 → 高可信
3. 在小豆邀请码主题的帖子 / 评论里独立出现的 6 位大写字母数字 → 中可信
4. 自动解析「有效期至 11 月 26 日 14:17」「有效期至：2026-11-26 14:17」，过期的码自动下架
5. 回复里出现“用了 / 没了 / 领完 / 失效”等字样 → 标“评论区说已被领”
6. 带“出售 / 押金 / 闲鱼 / 加群 / 私信”等字样 → 标“疑似售卖 / 引流”
7. 过滤 DOUBAO、123456 之类的误识别

## 一次性设置（大约 2 分钟）

代码已经全部放在仓库里了，只需要在 GitHub 网页上操作几步：

0. **启用定时任务文件**（GitHub 规定工作流文件只能由有 workflow 权限的账号写入，所以这一步要你手动点一下）：
   打开仓库的 `deploy/radar.yml` → 全选复制内容 → 回到仓库首页点 **Add file → Create new file** → 文件名填 `.github/workflows/radar.yml` → 粘贴 → **Commit changes**
1. **打开 GitHub Pages**：仓库 → Settings → Pages → Build and deployment → Source 选 **GitHub Actions**
2. **允许 Actions 写仓库**：Settings → Actions → General → Workflow permissions 选 **Read and write permissions** → Save
3. 到 Actions 页面，选「小豆邀请码雷达」→ **Run workflow** 手动跑第一次
4. 跑完后网页地址是：`https://chengpt2025-hub.github.io/xiaodouzhuama/`

### 运行频率说明

仓库是公开的，GitHub Actions 不限时长、Pages 免费，所以默认配置是**每 5 分钟触发一次、每次连扫 3 轮（间隔 60 秒）**，相当于大约每 1~2 分钟就扫一遍。GitHub 定时任务高峰期偶尔会延迟几分钟，属正常现象；想更实时就迁到自己服务器用 `crontab` 每分钟跑。

仓库里没有任何密钥。如果以后配置 `WEIBO_COOKIE`，它存放在仓库 Secret 里，公开仓库也不会泄露。

## 可调参数

在 Settings → Secrets and variables → Actions 里设置：

| 名称 | 类型 | 默认 | 作用 |
|---|---|---|---|
| `RADAR_KEYWORDS` | Variable | `小豆邀请码,小豆 邀请码,小豆邀请` | 搜索关键词，英文逗号分隔 |
| `RADAR_LOOPS` | Variable | `3` | 每次运行内连扫几轮（每轮间隔 60 秒） |
| `WEIBO_COOKIE` | Secret | 空 | 填了就启用微博源（可选，需要登录态，和“免登录”原则冲突，默认不开） |

本地 / 服务器上还可以用环境变量：`RADAR_SOURCES`（启用哪些源，如 `bilibili,tieba`）、`RADAR_LOOKBACK_HOURS`（往回看多少小时，默认 48）、`RADAR_KEEP_HOURS`（码保留多久，默认 72）、`RADAR_BILI_VIDEOS`（每个关键词抓多少条视频的评论，默认 12）。

## 迁移到自己的服务器

```bash
git clone https://github.com/chengpt2025-hub/xiaodouzhuama.git
cd xiaodouzhuama
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 先手动跑一次
.venv/bin/python radar/main.py --out site/data/codes.json

# 每 2 分钟一次（国内服务器访问 B 站 / 贴吧更稳）
crontab -e
*/2 * * * * cd /path/to/xiaodouzhuama && .venv/bin/python radar/main.py --out site/data/codes.json >> radar.log 2>&1
```

然后用 Nginx 把 `site/` 目录作为静态网站发布即可。

如果网页和数据不在同一个地方，在网页地址后面加参数指定数据地址：

```
https://你的网页地址/?data=https://你的数据地址/codes.json
```

例如直接读 GitHub 上 `data` 分支：

```
?data=https://raw.githubusercontent.com/chengpt2025-hub/xiaodouzhuama/data/codes.json
```

另外 `?fresh=30` 可以把“鲜码”的时间窗口从 10 分钟改成 30 分钟。

## 目录结构

```
deploy/radar.yml              定时任务模板：复制到 .github/workflows/radar.yml 后生效
radar/main.py                 主程序：调度各平台、合并历史、输出 codes.json
radar/sources.py              各平台免登录抓取源（B 站 / 贴吧 / 微博）
radar/extract.py              邀请码、有效期、已领 / 售卖识别
site/index.html               网页
site/app.js                   网页逻辑（自动刷新、筛选、复制）
site/style.css                iOS 风格样式，自动深浅色
site/data/codes.json          数据示例（线上以 data 分支为准）
requirements.txt              Python 依赖（只有 requests）
```

## codes.json 格式

```json
{
  "updated_at": "2026-11-26T19:50:00Z",
  "keywords": ["小豆邀请码"],
  "sources": {"bilibili": {"ok": true, "posts": 30}},
  "count": 1,
  "codes": [{
    "code": "D7QMPE",
    "posted_at": "2026-11-24T06:25:32Z",
    "first_seen": "2026-11-24T06:27:00Z",
    "expires_at": "2026-11-26T06:17:00Z",
    "source": "B站评论",
    "url": "原帖链接",
    "invite_link": "https://activity.doubao.com/ug/invite-share/M-D7QMPE",
    "confidence": "high",
    "suspect_used": false,
    "suspect_sale": false
  }]
}
```

## 关于小豆

小豆是豆包旗下的 AI 个人助理，独立 App，2026 年 11 月 24 日开启邀请制公测。邀请码为 6 位字母数字，一个码只能用一次，通常 2 天左右过期。拿到码后：下载「小豆」App → 登录 → 在等候名单页点「我有邀请码，马上去体验」→ 填 6 位码。

---

由 Bex 编写，按 xiansheng 的需求定制。
