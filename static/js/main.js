import { openAquarium } from "./aquarium.js";
import { startSpelling } from "./spelling.js";
import { startMatch } from "./match.js";
import { startSplit } from "./split.js";
import { openTrophies } from "./trophies.js";
import { $, api, el, setBalance, show } from "./ui.js";
import { startWriting } from "./writing.js";

const ACTIVITIES = {
  spelling: { icon: "🔤", name: "Spelling", blurb: "25 words", start: startSpelling },
  writing: { icon: "✍️", name: "Writing", blurb: "Answer today's question", start: startWriting },
  split: { icon: "✂️", name: "Sound splitting", blurb: "Count and split the sounds", start: startSplit },
  match: { icon: "👂", name: "Sound match", blurb: "Find words with a sound", start: startMatch },
};

let picked = new Set();

async function loadHome() {
  const h = await api("/api/home");
  show("home");
  setBalance(h.balance);
  drawWeek(h.week);
  const m = h.mission;
  const chosen = m.chosen;
  $("choose").hidden = Boolean(chosen);
  $("mission-list").hidden = !chosen;
  $("mission-done").hidden = !m.completed_at;
  if (!chosen) return drawChoices(h);

  const extras = h.extras.filter((a) => !chosen.includes(a));
  $("mission-list").replaceChildren(
    ...chosen.map((a) => activityRow(a, m.done[a], false, h.repeat_credits, h.saved[a])),
    ...(m.completed_at && extras.length
      ? [el("p", { class: "muted bonus-title" }, "Bonus practice:"),
         ...extras.map((a) => activityRow(a, m.done[a], true, h.repeat_credits, h.saved[a]))]
      : []));
}

function activityRow(id, done, bonus, repeatCredits, saved) {
  const a = ACTIVITIES[id];
  // Writing is once a day; games can be replayed for bonus credits.
  const replay = saved ? `Continue · ${saved}`
    : id === "writing" ? "Done for today" : repeatCredits ? `Done · play again for +${repeatCredits} 🪙` : "Done · play again for fun";
  return el("button", {
    class: `mission-item${done ? " done" : ""}${bonus ? " bonus" : ""}`,
    onclick: () => a.start(loadHome),
  },
    el("span", { class: "mi-icon" }, done ? "✓" : a.icon),
    el("span", { class: "mi-text" }, el("strong", {}, a.name),
       el("span", { class: "muted" }, done ? replay : saved ? `Continue · ${saved}` : a.blurb)),
    el("span", { class: "mi-go" }, done ? "" : "▶"));
}

function drawChoices(h) {
  picked = new Set();
  const range = h.min_extras === h.max_extras ? `${h.min_extras}` : `${h.min_extras} or ${h.max_extras}`;
  $("choose-range").textContent = range;
  const options = h.extras.filter((a) => a !== "writing" || h.has_prompts);
  $("extra-cards").replaceChildren(...options.map((id) => {
    const a = ACTIVITIES[id];
    const soon = !h.extras.includes(id);
    const card = el("button", {
      class: "choice-card", disabled: soon, "aria-pressed": "false",
      onclick: () => {
        if (picked.has(id)) picked.delete(id);
        else if (picked.size < h.max_extras) picked.add(id);
        for (const c of $("extra-cards").children) c.setAttribute("aria-pressed", String(picked.has(c.dataset.id)));
        $("choose-go").disabled = picked.size < h.min_extras;
      },
    }, el("span", { class: "cc-icon" }, a.icon), el("strong", {}, a.name),
       el("span", { class: "muted" }, soon ? "Coming soon" : a.blurb));
    card.dataset.id = id;
    return card;
  }));
  $("choose-go").disabled = true;
  $("choose-go").onclick = async () => {
    await api("/api/mission/choose", { extras: [...picked] });
    loadHome();
  };
}

function drawWeek(w) {
  $("week-dots").replaceChildren(...w.days.map((d) => el("div", { class: `day${d.done ? " done" : ""}${d.today ? " today" : ""}` },
    el("span", { class: "dot-mark" }, d.done ? "★" : ""), el("span", { class: "day-name" }, d.weekday[0]))));
  $("week-text").textContent = w.met
    ? `🎉 Weekly goal reached! ${w.count} of ${w.goal} days`
    : `${w.count} of ${w.goal} days this week`;
}

$("open-aquarium").onclick = openAquarium;
$("open-trophies").onclick = openTrophies;
for (const b of document.querySelectorAll("[data-home]")) b.onclick = loadHome;

loadHome();
