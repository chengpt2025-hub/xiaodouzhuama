const qs = new URLSearchParams(location.search);
const DATA_URL = qs.get("data") || "data/codes.json";
const VOTE_API = "https://abacus.jasoncameron.dev";
const VOTE_NS = "xiaodou-radar-v1";
const NEW_MIN = 30, FRESH_MIN = 10;
const $ = (s) => document.querySelector(s);
let data = null, plat = "", rangeMin = 0;
const votes = {};
const mine = JSON.parse(localStorage.getItem("xd_votes") || "{}");

const minsAgo = (iso) => (Date.now() - new Date(iso)) / 60000;
function agoText(iso) {
  const m = minsAgo(iso);
  if (m < 1) return "刚刚";
  if (m < 60) return `${Math.floor(m)} 分钟前`;
  if (m < 1440) return `${Math.floor(m / 60)} 小时 ${Math.floor(m % 60)} 分钟前`;
  return `${Math.floor(m / 1440)} 天前`;
}
const hm = (iso) => new Date(iso).toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit", timeZone: "Asia/Shanghai" });
const md = (iso) => new Date(iso).toLocaleString("zh-CN", { hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Shanghai" });
const full = (iso) => new Date(iso).toLocaleString("zh-CN", { hour12: false, year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Shanghai" });
const toast = (t) => { const e = $("#toast"); e.textContent = t; e.classList.add("show"); clearTimeout(e._t); e._t = setTimeout(() => e.classList.remove("show"), 1600); };
const timeOf = (c) => new Date(c.posted_at || c.first_seen);
const platName = (p) => ({ X: "X 帖", "微博": "微博", "抖音": "抖音评论", "B站": "B站", "百度贴吧": "贴吧" }[p] || p || "网页");

function status(c) {
  const v = votes[c.code] || { ok: 0, bad: 0 };
  if (c.expires_at && new Date(c.expires_at) < Date.now()) return { cls: "b-exp", t: "已过期", dead: true };
  if (v.bad && v.bad >= v.ok) return { cls: "b-bad", t: `${v.bad} 人说已被用`, dead: v.bad >= 2 };
  if (v.ok) return { cls: "b-ok", t: `${v.ok} 人说能用`, dead: false };
  if (c.suspect_used) return { cls: "b-bad", t: "评论说已被领", dead: false };
  return { cls: "b-wait", t: "待验证", dead: false };
}
function score(c) {
  const s = status(c); if (s.dead) return -1;
  const v = votes[c.code] || { ok: 0, bad: 0 };
  return (c.posted_at ? 1000 - minsAgo(c.posted_at) : 0) + v.ok * 30 - v.bad * 60 - (c.suspect_used ? 200 : 0);
}

async function load() {
  try {
    const r = await fetch(`${DATA_URL}${DATA_URL.includes("?") ? "&" : "?"}t=${Date.now()}`, { cache: "no-store" });
    data = await r.json(); render(); loadVotes();
  } catch { $("#updated").textContent = "加载失败，稍后自动重试"; }
}
async function getCount(k) {
  try { const r = await fetch(`${VOTE_API}/get/${VOTE_NS}/${k}`); return r.ok ? (await r.json()).value || 0 : 0; } catch { return 0; }
}
async function loadVotes() {
  const list = [...data.codes].sort((a, b) => timeOf(b) - timeOf(a)).slice(0, 80);
  for (let i = 0; i < list.length; i += 8) {
    await Promise.all(list.slice(i, i + 8).map(async (c) => {
      const [ok, bad] = await Promise.all([getCount(`ok-${c.code}`), getCount(`bad-${c.code}`)]);
      votes[c.code] = { ok, bad };
    }));
  }
  render();
}
async function vote(code, kind) {
  if (mine[code]) { toast("这个码你已经标记过了"); return; }
  try {
    const r = await fetch(`${VOTE_API}/hit/${VOTE_NS}/${kind}-${code}`);
    const v = (await r.json()).value;
    votes[code] = votes[code] || { ok: 0, bad: 0 }; votes[code][kind] = v;
    mine[code] = kind; localStorage.setItem("xd_votes", JSON.stringify(mine));
    toast(kind === "bad" ? "已标记为已被用，谢谢" : "已标记为能用，谢谢"); render();
  } catch { toast("标记失败，稍后再试"); }
}
async function copy(code) {
  try { await navigator.clipboard.writeText(code); toast(`已复制 ${code}`); }
  catch { toast("复制失败，请长按邀请码手动复制"); }
}

function rowHTML(c, hero = false) {
  const st = status(c), v = votes[c.code] || { ok: 0, bad: 0 };
  let when;
  if (c.posted_at) {
    const m = minsAgo(c.posted_at), est = c.time_source !== "原帖时间";
    when = `<span class="when ${m < FRESH_MIN ? "fresh" : ""}">${est ? "约 " : ""}${agoText(c.posted_at)}发出</span>`;
  } else when = `<span class="when">发布时间未知</span>`;
  const via = c.via ? ` · 经${c.via}` : "";
  const exp = c.expires_at ? (new Date(c.expires_at) > Date.now() ? ` · 有效至 ${md(c.expires_at)}` : " · 已过有效期") : "";
  return `
    <span class="code">${c.code}</span>
    <span class="meta"><span class="badge ${st.cls}">${st.t}</span><span class="plat">${platName(c.platform)}</span>${when}</span>
    <span class="acts">
      <button class="btn copy" data-a="copy">复制</button>
      ${hero ? `<a class="btn go" href="${c.invite_link}" target="_blank" rel="noopener noreferrer">去兑换</a>` : ""}
      <button class="btn used ${mine[c.code] === "bad" ? "on" : ""}" data-a="bad">已被用${v.bad ? ` <b>${v.bad}</b>` : ""}</button>
      <button class="btn ok ${mine[c.code] === "ok" ? "on" : ""}" data-a="ok">能用${v.ok ? ` <b>${v.ok}</b>` : ""}</button>
    </span>
    <span class="sub2">查到于 ${md(c.first_seen)}${c.posted_at ? ` · 发布于 ${md(c.posted_at)}` : ""}${via}${exp}</span>`;
}
function bind(el, c) {
  el.querySelectorAll("[data-a]").forEach((b) => {
    b.onclick = () => b.dataset.a === "copy" ? copy(c.code) : vote(c.code, b.dataset.a);
  });
}

function render() {
  if (!data) return;
  $("#updated").textContent = full(data.updated_at);
  const all = data.codes.filter((c) => !(c.expires_at && new Date(c.expires_at) < Date.now() - 3600e3));
  const counts = {};
  all.forEach((c) => (counts[c.platform] = (counts[c.platform] || 0) + 1));
  const pl = $("#plats");
  pl.innerHTML = `<button data-p="" class="${plat ? "" : "on"}">全部 ${all.length}</button>` +
    Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([p, n]) => `<button data-p="${p}" class="${plat === p ? "on" : ""}">${platName(p)} ${n}</button>`).join("");
  pl.querySelectorAll("button").forEach((b) => (b.onclick = () => { plat = b.dataset.p; render(); }));

  const showDead = $("#showDead").checked;
  const list = all.filter((c) => (!plat || c.platform === plat)
      && (!rangeMin || minsAgo(c.posted_at || c.first_seen) <= rangeMin)
      && (showDead || !status(c).dead))
    .sort((a, b) => timeOf(b) - timeOf(a));
  const hiddenN = all.length - list.length;
  $("#summary").textContent = `共查到 ${all.length} 个码，当前显示 ${list.length} 个` +
    (hiddenN ? `（${hiddenN} 个被上面的时间范围 / 平台 / 状态条件隐藏，点「全部」并勾选“显示已被用”可看到全部）` : "");
  const isNew = (c) => c.posted_at && minsAgo(c.posted_at) <= NEW_MIN && !status(c).dead;
  const fresh = list.filter(isNew), old = list.filter((c) => !isNew(c));

  const best = [...fresh].sort((a, b) => score(b) - score(a))[0];
  const hero = $("#hero");
  if (best && score(best) > 0) {
    hero.hidden = false;
    hero.innerHTML = `<div class="lbl">先试这个</div><div class="row">${rowHTML(best, true)}</div>`;
    bind(hero, best);
  } else hero.hidden = true;

  const fill = (ul, arr) => {
    ul.innerHTML = "";
    arr.forEach((c) => {
      const li = document.createElement("li");
      li.className = "row" + (status(c).dead ? " dead" : "");
      li.innerHTML = rowHTML(c); bind(li, c); ul.append(li);
    });
  };
  const freshRest = fresh.filter((c) => c !== best);
  fill($("#newList"), freshRest);
  $("#newCount").textContent = `· ${fresh.length} 条`;
  $("#newNone").hidden = fresh.length > 0;
  $("#newList").hidden = freshRest.length === 0;
  fill($("#oldList"), old);
  $("#oldCount").textContent = `· ${old.length} 条`;
}

$("#range").onclick = (e) => {
  const b = e.target.closest("button"); if (!b) return;
  document.querySelectorAll("#range button").forEach((x) => x.classList.toggle("on", x === b));
  rangeMin = Number(b.dataset.v); render();
};
$("#showDead").onchange = render;
$("#refresh").onclick = () => { load(); toast("已刷新"); };
load();
setInterval(load, 30000);
setInterval(render, 20000);
