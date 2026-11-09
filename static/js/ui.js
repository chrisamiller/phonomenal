// Shared helpers: API calls, screen switching, and reward pop-ups.
export const $ = (id) => document.getElementById(id);

export async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {   // signed out (e.g. the cookie expired): back to the sign-in page
    location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
    throw new Error("Please sign in");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${path}: ${res.status}`);
  return data;
}

const SCREENS = ["home", "quiz", "done", "writing", "split", "match", "aquarium", "trophies"];
const leaveHooks = {};

export function show(screen) {
  for (const id of SCREENS) {
    if (!$(id).hidden && id !== screen) leaveHooks[id]?.();
    $(id).hidden = id !== screen;
  }
  $("home-links").hidden = screen !== "home";
  window.scrollTo(0, 0);
}

// ---- saved progress (per activity, for today; the server drops it after midnight) ----
let saveChain = Promise.resolve();

export async function loadSaved(name) {
  try { return (await api(`/api/saved/${name}`)).state; } catch { return null; }
}

// Saves run one after another so an older state never lands after a newer one.
export function saveProgress(name, state) {
  const body = { state: state && { ...state, tally: activity } };
  saveChain = saveChain.then(() => api(`/api/saved/${name}`, body)).catch(() => {});
  return saveChain;
}

export const savesDone = () => saveChain;

export function onLeave(screen, fn) { leaveHooks[screen] = fn; }

export function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "html") e.innerHTML = v;
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  e.append(...children.flat().filter((c) => c != null));
  return e;
}

// ---- reward pop-ups ----
const queue = [];
let showing = false;
let activity = null;   // rewards collected during the current game, for its completion page

// `tally` restores the rewards collected before a reload.
export function beginActivity(tally = null) { activity = tally || { credits: 0, achievements: [] }; }

export function celebrate(awards = [], { quietAchievements = false } = {}) {
  for (const a of awards) {
    if (activity && a.kind === "credits") activity.credits += a.amount;
    if (activity && a.kind === "achievement") activity.achievements.push(a);
    if (a.kind === "credits") coinGain(a.amount);                      // "+N 🪙" by the coin counter
    else if (a.kind === "achievement" && !quietAchievements) achievementToast(a);  // else on the completion page
  }
}

// Achievements stay up until she taps them.
function achievementToast(a) {
  const t = el("button", { class: "toast achievement", "aria-label": `${a.name}. Tap to close.` },
    el("div", { class: "toast-icon" }, "🏆"),
    el("div", {}, el("strong", {}, a.name + (a.tier ? ` · ${a.tier}` : "") + (a.times > 1 ? ` ×${a.times}` : "")),
      el("div", {}, a.description),
      a.credits ? el("div", { class: "toast-credits" }, `+${a.credits} 🪙`) : null,
      el("div", { class: "toast-hint" }, "Tap to close")));
  t.addEventListener("click", () => t.remove());
  $("toasts").append(t);
}

function next() {
  const a = queue.shift();
  if (!a) { showing = false; return; }
  showing = true;
  const t = el("div", { class: "toast" }, a.message);
  $("toasts").append(t);
  const close = () => { t.remove(); next(); };
  t.addEventListener("click", close);
  setTimeout(close, 1600);
}

// ---- coin counter (in the header on every screen) ----
let balanceShown = null;   // what the counter shows; moves with each "+N" animation
const gains = [];
let animating = false;

export function setBalance(n) {
  if (animating || gains.length) return;   // mid-animation: the queued gains will land on the right total
  balanceShown = n;
  $("balance").textContent = n;
}

function coinGain(amount) {
  if (!amount) return;
  gains.push(amount);
  if (!animating) nextGain();
}

function nextGain() {
  const amount = gains.shift();
  if (amount === undefined) { animating = false; refreshBalance(); return; }
  animating = true;
  const pill = $("credits-pill");
  const float = el("span", { class: `coin-float${amount < 0 ? " spend" : ""}` }, `${amount > 0 ? "+" : ""}${amount} 🪙`);
  pill.append(float);
  setTimeout(() => {            // the total ticks over as the "+N" reaches it
    balanceShown = (balanceShown ?? 0) + amount;
    $("balance").textContent = balanceShown;
    pill.classList.remove("bump");
    void pill.offsetWidth;
    pill.classList.add("bump");
  }, 650);
  setTimeout(() => { float.remove(); nextGain(); }, 1100);
}

// Completion page shared by every game: summary, credits and achievements earned during it.
export function showComplete({ title = "Great work! 🎉", summary = "", list = [] }, finalAwards, onBack) {
  celebrate(finalAwards, { quietAchievements: true });
  const got = activity || { credits: 0, achievements: [] };
  activity = null;
  show("done");
  $("done-title").textContent = title;
  $("summary").textContent = summary;
  $("done-list").replaceChildren(...list.map((t) => el("li", {}, t)));
  $("done-credits").hidden = !got.credits;
  $("done-credits").textContent = `+${got.credits} 🪙 credits earned`;
  $("done-awards").replaceChildren(...got.achievements.map((a) => el("div", { class: "done-award" },
    el("span", { class: "toast-icon" }, "🏆"),
    el("div", {}, el("strong", {}, a.name + (a.tier ? ` · ${a.tier}` : "") + (a.times > 1 ? ` ×${a.times}` : "")),
      el("div", { class: "muted" }, a.description)))));
  $("done-home").onclick = onBack;
  $("done-home").focus();
}

export function notify(message) {
  queue.push({ kind: "note", message });
  if (!showing) next();
}

export async function refreshBalance() {
  try { setBalance((await api("/api/balance")).balance); } catch { /* offline: leave as is */ }
}

// ---- bottom sheet (shop, gallery, dialogs) ----
export function openSheet(title, { tabs = null, render }) {
  $("sheet-title").textContent = title;
  const tabBar = $("sheet-tabs");
  tabBar.replaceChildren();
  let active = tabs ? tabs[0].id : null;
  const draw = () => {
    if (tabs) {
      tabBar.replaceChildren(...tabs.map((t) => el("button", {
        class: t.id === active ? "tab active" : "tab", onclick: () => { active = t.id; draw(); },
      }, t.label)));
    }
    $("sheet-body").replaceChildren(...[render(active, draw)].flat());
  };
  draw();
  $("sheet").hidden = false;
  return { redraw: draw, close: closeSheet };
}

export function closeSheet() { $("sheet").hidden = true; }
$("sheet-close").onclick = closeSheet;
$("sheet").addEventListener("click", (e) => { if (e.target === $("sheet")) closeSheet(); });
