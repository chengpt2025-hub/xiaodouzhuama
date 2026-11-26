const qs = new URLSearchParams(location.search);
const DATA_URL = qs.get("data") || "data/codes.json";
// 游客打标：免登录的开源计数服务（每个码两个计数器：能用 / 失效）
const VOTE_API = "https://abacus.jasoncameron.dev";
const VOTE_NS = "xiaodou-radar-v1";
const $ = (s) => document.querySelector(s);
let data = null, windowMin = 10;
const votes = {};               // code -> {ok, bad}
const mine = JSON.parse(localStorage.getItem("xd_votes") || "{}");

const ago = (iso) => {
  const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  if (s < 60) return "刚刚";
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时 ${Math.floor((s % 3600) / 60)} 分前`;
  return `${Math.floor(s / 86400)} 天前`;
};
const fmt = (iso) => new Date(iso).toLocaleString("zh-CN", { hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
const left = (iso) => {
  const m = (new Date(iso) - Date.now()) / 60000;
  if (m <= 0) return null;
  return m < 60 ? `还剩 ${Math.floor(m)} 分钟` : `还剩 ${Math.floor(m / 60)} 小时`;
};
const toast = (t) => { const el = $("#toast"); el.textContent = t; el.classList.add("show"); clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("show"), 1600); };
const timeOf = (c) => new Date(c.posted_at || c.first_seen);

// 可用可能性：综合发布时长、有效期、是否被说已领、来源类型和游客打标
function chance(c) {
  const now = Date.now();
  if (c.expires_at && new Date(c.expires_at) < now) return { s: 0, label: "已过期", cls: "c1" };
  const ageMin = (now - timeOf(c)) / 60000;
  let s = !c.posted_at ? 0.3 : ageMin < 10 ? 0.9 : ageMin < 30 ? 0.7 : ageMin < 120 ? 0.45 : ageMin < 360 ? 0.25 : 0.12;
  if (c.confidence !== "high") s *= 0.85;
  if (c.aggregator) s *= 0.7;
  if (c.suspect_sale) s *= 0.5;
  if (c.suspect_used) s = Math.min(s, 0.12);
  const v = votes[c.code] || { ok: 0, bad: 0 };
  if (v.bad || v.ok) s = s * Math.pow(0.55, v.bad) + (1 - s) * (v.ok / (v.ok + v.bad + 1)) * 0.6;
  if (v.bad >= 3 && v.bad > v.ok * 2) s = Math.min(s, 0.05);
  const label = s >= 0.6 ? "很可能可用" : s >= 0.35 ? "可能可用" : s >= 0.15 ? "可能已被领" : "大概率失效";
  return { s, label, cls: s >= 0.6 ? "c4" : s >= 0.35 ? "c3" : s >= 0.15 ? "c2" : "c1" };
}

async function load() {
  try {
    const r = await fetch(`${DATA_URL}${DATA_URL.includes("?") ? "&" : "?"}t=${Date.now()}`, { cache: "no-store" });
    data = await r.json();
    render();
    loadVotes();
  } catch (e) {
    $("#meta").textContent = "数据加载失败，稍后自动重试";
  }
}

async function getCount(key) {
  try {
    const r = await fetch(`${VOTE_API}/get/${VOTE_NS}/${key}`);
    if (!r.ok) return 0;
    return (await r.json()).value || 0;
  } catch { return 0; }
}
async function loadVotes() {
  const list = data.codes.slice(0, 120);
  for (let i = 0; i < list.length; i += 8) {
    await Promise.all(list.slice(i, i + 8).map(async (c) => {
      const [ok, bad] = await Promise.all([getCount(`ok-${c.code}`), getCount(`bad-${c.code}`)]);
      votes[c.code] = { ok, bad };
    }));
  }
  render();
}
async function vote(code, kind, btn) {
  if (mine[code]) { toast("你已经标记过这个码了"); return; }
  btn.disabled = true;
  try {
    const r = await fetch(`${VOTE_API}/hit/${VOTE_NS}/${kind}-${code}`);
    const v = (await r.json()).value;
    votes[code] = votes[code] || { ok: 0, bad: 0 };
    votes[code][kind] = v;
    mine[code] = kind;
    localStorage.setItem("xd_votes", JSON.stringify(mine));
    toast(kind === "bad" ? "已标记为失效，谢谢" : "已标记为能用，谢谢");
    render();
  } catch {
    toast("标记失败，稍后再试");
    btn.disabled = false;
  }
}

function stat(n, t) { return `<div class="stat"><b>${n}</b><span>${t}</span></div>`; }

function render() {
  if (!data) return;
  const now = Date.now();
  const st = data.stats || {};
  const live = data.codes.filter((c) => !(c.expires_at && new Date(c.expires_at) < now));
  const fresh = live.filter((c) => c.posted_at && now - new Date(c.posted_at) < 10 * 60000).length;
  const plats = [...new Set(data.codes.map((c) => c.platform))];
  $("#meta").textContent = `上次查询 ${fmt(data.updated_at)}（${ago(data.updated_at)}）· 覆盖 ${plats.length} 个平台`;
  $("#stats").innerHTML = stat(fresh, "10 分钟内新码") + stat(st.found_24h ?? live.length, "24 小时内发现") +
    stat(live.length, "当前追踪中") + stat(st.new_this_scan ?? 0, "本次查询新增");

  const sel = $("#plat"), cur = sel.value;
  sel.innerHTML = '<option value="">全部平台</option>' + plats.map((p) => `<option>${p}</option>`).join("");
  sel.value = plats.includes(cur) ? cur : "";

  let list = data.codes.map((c) => ({ c, k: chance(c) })).filter(({ c, k }) => {
    if (windowMin && (!c.posted_at || now - new Date(c.posted_at) > windowMin * 60000)) return false;
    if (sel.value && c.platform !== sel.value) return false;
    if ($("#hideBad").checked && k.s < 0.15) return false;
    return true;
  });
  list.sort($("#sort").value === "chance" ? (a, b) => b.k.s - a.k.s : (a, b) => timeOf(b.c) - timeOf(a.c));

  const box = $("#list");
  box.innerHTML = "";
  $("#empty").hidden = list.length > 0;
  $("#empty").textContent = windowMin
    ? `最近 ${windowMin >= 60 ? windowMin / 60 + " 小时" : windowMin + " 分钟"}内还没有查到能确定发布时间的新码，可以切换到更长的时间范围看看。`
    : "暂时没有符合条件的码。";

  const tpl = $("#card");
  for (const { c, k } of list) {
    const n = tpl.content.cloneNode(true);
    const card = n.querySelector(".card");
    if (c.posted_at && now - new Date(c.posted_at) <= 10 * 60000 && k.s >= 0.35) card.classList.add("fresh");
    if (k.s < 0.15) card.classList.add("dead");
    n.querySelector(".code").textContent = c.code;
    const ch = n.querySelector(".chance");
    ch.textContent = k.label; ch.className = "chance " + k.cls;

    const chips = n.querySelector(".chips");
    const chip = (t, cls = "") => { const s = document.createElement("span"); s.className = "chip " + cls; s.textContent = t; chips.append(s); };
    chip(c.platform, "plat");
    (c.seen_on || []).filter((p) => p !== c.platform).forEach((p) => chip("也见于 " + p));
    if (c.suspect_used) chip("有人说已被领", "bad");
    if (c.suspect_sale) chip("疑似售卖", "warn");
    const v = votes[c.code];
    if (v && v.bad) chip(`${v.bad} 人反馈失效`, "bad");

    const dl = n.querySelector(".times");
    const row = (dt, dd) => { const a = document.createElement("dt"); a.textContent = dt; const b = document.createElement("dd"); b.innerHTML = dd; dl.append(a, b); };
    if (c.posted_at) {
      const how = c.time_source === "原帖时间" ? "平台原帖时间" : `按页面“${c.time_text || ""}”推算`;
      row("发布", `${fmt(c.posted_at)}（${ago(c.posted_at)}）<span class="note">${how}</span>`);
    } else {
      row("发布", `未知<span class="note">出处未写发布时间</span>`);
    }
    row("查询到", `${fmt(c.first_seen)}（${ago(c.first_seen)}）`);
    if (c.last_seen && c.last_seen !== c.first_seen) row("最近一次", `${fmt(c.last_seen)} 仍能查到`);
    if (c.expires_at) {
      const l = left(c.expires_at);
      row("有效期至", `${fmt(c.expires_at)}${l ? `（${l}）` : ` <span class="red">已过期</span>`}`);
    }

    n.querySelector(".go").href = c.invite_link;
    n.querySelector(".copy").onclick = async () => {
      try { await navigator.clipboard.writeText(c.code); toast(`已复制 ${c.code}`); }
      catch { toast("复制失败，请手动长按复制"); }
    };
    const ok = n.querySelector(".ok"), bad = n.querySelector(".bad");
    ok.querySelector("b").textContent = v ? v.ok : 0;
    bad.querySelector("b").textContent = v ? v.bad : 0;
    if (mine[c.code] === "ok") ok.classList.add("voted");
    if (mine[c.code] === "bad") bad.classList.add("voted");
    ok.onclick = () => vote(c.code, "ok", ok);
    bad.onclick = () => vote(c.code, "bad", bad);
    box.append(n);
  }
}

$("#seg").onclick = (e) => {
  const b = e.target.closest("button"); if (!b) return;
  document.querySelectorAll("#seg button").forEach((x) => x.classList.toggle("on", x === b));
  windowMin = Number(b.dataset.v); render();
};
["#plat", "#sort", "#hideBad"].forEach((s) => ($(s).onchange = render));
load();
setInterval(load, 30000);
setInterval(render, 20000);
