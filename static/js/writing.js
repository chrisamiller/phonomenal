import { $, api, beginActivity, el, loadSaved, saveProgress, savesDone, show, showComplete } from "./ui.js";

let cfg = null;
let started = null;
let onFinished = null;

// Rough sentence count: chunks ending in . ! ? (plus any unfinished last sentence).
function countSentences(text) {
  return text.trim().split(/[.!?]+(?:\s|$)/).filter((s) => /[A-Za-z]/.test(s)).length;
}
const countWords = (text) => (text.match(/[A-Za-z0-9'’]+/g) || []).length;

function update() {
  const text = $("writing-text").value;
  const n = countSentences(text);
  const goal = cfg.min_sentences;
  $("sentence-dots").replaceChildren(...Array.from({ length: Math.max(goal + 1, n) }, (_, i) =>
    el("span", { class: i < n ? "dot on" : "dot" })));
  $("writing-done").disabled = !(n >= goal || countWords(text) >= cfg.min_words);
}

export async function startWriting(finished) {
  onFinished = finished;
  const saved = await loadSaved("writing");
  beginActivity(saved?.tally);
  cfg = await api("/api/writing/today");
  show("writing");
  $("prompt-text").textContent = cfg.prompt.text;
  $("writing-already").hidden = !cfg.done;
  $("writing-text").hidden = cfg.done;
  $("writing-done").parentElement.hidden = cfg.done;
  if (cfg.done) return;
  // A draft from earlier today comes back after a reload.
  $("writing-text").value = saved?.text || "";
  started = saved?.started || new Date().toISOString();
  update();
  $("writing-text").focus();
}

async function submit() {
  $("writing-done").disabled = true;
  clearTimeout(draftTimer);
  await savesDone();
  try {
    const r = await api("/api/writing/submit", { text: $("writing-text").value, started });
    showComplete({ title: "Nice writing! ✍️",
                   summary: `You wrote ${r.words} words in ${r.sentences} sentence${r.sentences === 1 ? "" : "s"}.` },
                 r.awards, onFinished);
  } catch (e) {
    $("writing-done").disabled = false;
    alertInline(e.message);
  }
}

function alertInline(msg) {
  const p = el("p", { class: "note" }, msg);
  $("writing-done").parentElement.after(p);
  setTimeout(() => p.remove(), 4000);
}

let draftTimer = null;
$("writing-text").addEventListener("input", () => {
  update();
  clearTimeout(draftTimer);   // save the draft a moment after she stops typing
  draftTimer = setTimeout(() => {
    const text = $("writing-text").value;
    saveProgress("writing", { text, started, label: `${countWords(text)} words written` });
  }, 800);
});
$("writing-done").onclick = submit;
