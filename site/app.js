const params = new URLSearchParams(location.search);
const DATA_URL = params.get("data") || "data/codes.json";
const FRESH_MIN = Number(params.get("fresh") || 10);
const $ = (s) => document.querySelector(s);
$("#dataUrl").textContent = DATA_URL;
let data = null;

const ago = (iso) => {
  const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  if (s < 60) return `${Math.floor(s)} 秒前`;
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  return `${Math.floor(s / 86400)} 天前`;
};
const fmt = (iso) => new Date(iso).toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });

async function load() {
  try {
    const r = await fetch(`${DATA_URL}${DATA_URL.includes("?") ? "&" : "?"}t=${Date.now()}`, { cache: "no-store" });
    data = await r.json();
    render();
  } catch (e) {
    $("#meta").textContent = "数据加载失败：" + e.message;
  }
}

function render() {
  if (!data) return;
  $("#meta").textContent = `雷达上次扫描：${fmt(data.updated_at)}（${ago(data.updated_at)}） · 共 ${data.count} 个码 · 关键词：${data.keywords.join(" / ")}`;
  const srcBox = $("#sources");
  srcBox.innerHTML = "";
  const names = { bilibili: "B站", tieba: "百度贴吧", douyin: "抖音", xiaohongshu: "小红书", web: "全网检索", weibo: "微博" };
  for (const [k, v] of Object.entries(data.sources || {})) {
    const el = document.createElement("span");
    el.className = v.ok ? "ok" : "bad";
    el.textContent = `${names[k] || k}：${v.ok ? "正常 · " + v.posts + " 条" : "暂不可用"}`;
    if (!v.ok) el.title = v.error;
    srcBox.append(el);
  }
  const sel = $("#src");
  const cur = sel.value;
  const plats = [...new Set(data.codes.map((c) => c.source))];
  sel.innerHTML = '<option value="">全部平台</option>' + plats.map((p) => `<option>${p}</option>`).join("");
  sel.value = cur;

  const now = Date.now();
  const list = data.codes.filter((c) => {
    if ($("#fresh").checked && now - new Date(c.posted_at) > FRESH_MIN * 60000) return false;
    if ($("#hideUsed").checked && (c.suspect_used || c.suspect_sale)) return false;
    if ($("#hideAgg").checked && c.aggregator) return false;
    if (c.expires_at && new Date(c.expires_at) < now) return false;
    if (sel.value && c.source !== sel.value) return false;
    return true;
  });
  const box = $("#list");
  box.innerHTML = "";
  $("#empty").hidden = list.length > 0;
  const tpl = $("#card");
  for (const c of list) {
    const n = tpl.content.cloneNode(true);
    const card = n.querySelector(".card");
    if (now - new Date(c.posted_at) <= FRESH_MIN * 60000) card.classList.add("fresh");
    n.querySelector(".code").textContent = c.code;
    n.querySelector(".go").href = c.invite_link;
    n.querySelector(".copy").onclick = async (e) => {
      await navigator.clipboard.writeText(c.code);
      e.target.textContent = "已复制";
      setTimeout(() => (e.target.textContent = "复制"), 1500);
    };
    const tags = n.querySelector(".tags");
    const add = (t, cls = "") => { const s = document.createElement("span"); s.textContent = t; s.className = cls; tags.append(s); };
    add(c.source);
    add(c.confidence === "high" ? "高可信" : "中可信", c.confidence === "high" ? "g" : "");
    if (c.expires_at) add("有效期至 " + fmt(c.expires_at), "o");
    if (c.suspect_used) add("评论区说已被领", "r");
    if (c.suspect_sale) add("疑似售卖/引流", "r");
    if (c.aggregator) add("来自抓码聚合站", "o");
    if (c.seen_count > 1) add(`${c.seen_count} 处出现`);
    n.querySelector(".snippet").textContent = c.snippet;
    n.querySelector(".origin").href = c.url;
    n.querySelector(".time").textContent = c.time_estimated ? `首次发现于 ${ago(c.first_seen)}` : `发布于 ${ago(c.posted_at)}`;
    box.append(n);
  }
}

$("#fresh").onchange = render;
$("#hideUsed").onchange = render;
$("#hideAgg").onchange = render;
$("#src").onchange = render;
$("#reload").onclick = load;
load();
setInterval(load, 30000);
setInterval(render, 15000);
