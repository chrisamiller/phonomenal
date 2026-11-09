import { $, api, el, show } from "./ui.js";

export async function openTrophies() {
  const t = await api("/api/trophies");
  show("trophies");
  const today = t.items.filter((i) => i.today).length;
  $("trophy-count").textContent = `${t.items.length} earned` + (today ? ` · ${today} today!` : "") +
    ` · ${t.unearned} more to discover`;
  $("trophy-empty").hidden = t.items.length > 0;
  $("trophy-grid").replaceChildren(...t.items.map((i) => el("div", { class: i.today ? "trophy earned today" : "trophy earned" },
    i.today ? el("span", { class: "trophy-new" }, "New today!") : null,
    el("div", { class: "trophy-icon" }, i.hidden ? "🌟" : "🏆"),
    el("strong", {}, i.name + (i.times > 1 ? ` ×${i.times}` : "")),
    el("div", { class: "muted" }, i.description),
    i.tiers ? el("div", { class: "tiers" }, ...i.tiers.map((n) =>
      el("span", { class: i.earned_tiers.includes(n) ? "tier on" : "tier" }, String(n)))) : null)));
}
