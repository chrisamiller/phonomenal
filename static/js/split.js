import { $, api, beginActivity, el, loadSaved, saveProgress, savesDone, show, showComplete } from "./ui.js";

// Sound splitting: "How many sounds?" then tap the gaps between letters to split the word.
let s = null;
let onFinished = null;

export async function startSplit(finished) {
  onFinished = finished;
  const saved = await loadSaved("split");
  if (saved) {
    // Carry on after a reload; a word already checked moves on rather than being scored twice.
    beginActivity(saved.tally);
    s = { session: saved.session, words: saved.words, idx: saved.idx + (saved.answered ? 1 : 0),
          count: null, cuts: new Set(), right: saved.right };
  } else {
    beginActivity();
    const data = await api("/api/split/session", {});
    s = { session: data.session, words: data.words, idx: 0, count: null, cuts: new Set(), right: 0 };
  }
  show("split");
  if (s.idx >= s.words.length) return finish();
  showWord();
}

function save(answered = false) {
  const { session, words, idx, right } = s;
  saveProgress("split", { session, words, idx, right, answered,
                          label: `${idx + (answered ? 1 : 0)} of ${words.length} words` });
}

function showWord() {
  const w = s.words[s.idx];
  save();
  s.count = null;
  s.cuts = new Set();
  $("split-bar").style.width = `${(100 * s.idx) / s.words.length}%`;
  $("split-word").textContent = w.word;
  $("count-step").hidden = false;
  $("count-feedback").hidden = true;
  $("split-step").hidden = true;
  $("split-feedback").hidden = true;
  $("count-buttons").replaceChildren(...Array.from({ length: Math.min(8, w.word.length) }, (_, i) =>
    el("button", { class: "count-btn", "aria-pressed": "false", onclick: () => pickCount(i + 1) }, String(i + 1))));
}

// The number buttons stay up while she splits, so she can change her mind; the splits are kept.
function pickCount(n) {
  const first = s.count === null;
  s.count = n;
  [...$("count-buttons").children].forEach((b, i) => b.setAttribute("aria-pressed", String(i + 1 === n)));
  $("count-feedback").hidden = false;
  $("count-feedback").className = "feedback neutral";
  $("count-feedback").textContent = `You said ${n} sound${n === 1 ? "" : "s"}. Now show where they are.`;
  $("split-step").hidden = false;
  if (first) drawTiles();
}

function drawTiles() {
  const word = s.words[s.idx].word;
  const parts = [];
  [...word].forEach((ch, i) => {
    if (i > 0) {
      parts.push(el("button", {
        class: s.cuts.has(i) ? "gap cut" : "gap", "aria-label": `split before ${ch}`,
        onclick: () => { s.cuts.has(i) ? s.cuts.delete(i) : s.cuts.add(i); drawTiles(); },
      }, s.cuts.has(i) ? "|" : "┊"));
    }
    parts.push(el("span", { class: "tile" }, ch));
  });
  $("tiles").replaceChildren(...parts);
}

const COLORS = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"];

async function check() {
  const w = s.words[s.idx];
  const r = await api("/api/split/answer", { session: s.session, id: w.id, count: s.count, split: [...s.cuts] });
  s.right += r.count_ok && r.split_ok;
  save(true);
  $("split-step").hidden = true;
  $("count-step").hidden = true;
  const plural = (n) => `${n} sound${n === 1 ? "" : "s"}`;
  $("count-feedback").className = r.count_ok ? "feedback good" : "feedback bad";
  $("count-feedback").textContent = r.count_ok ? `Yes, ${w.word} has ${plural(r.count)}.`
    : `You said ${plural(s.count)}, but ${w.word} has ${plural(r.count)}.`;
  $("split-feedback").hidden = false;
  $("split-feedback").className = r.split_ok ? "feedback good" : "feedback bad";
  $("split-result").textContent = r.split_ok ? "Yes, here's how it splits:" : "Not quite. Compare the two:";
  // Her split, as plain tiles, above the right one so she can see the difference.
  $("split-yours").hidden = r.split_ok;
  const cuts = [0, ...[...s.cuts].sort((a, b) => a - b), w.word.length];
  $("split-yours-tiles").replaceChildren(...cuts.slice(1).flatMap((end, i) => [
    ...(i ? [el("span", { class: "gap cut static" }, "|")] : []),
    el("span", { class: "tile group" }, w.word.slice(cuts[i], end)),
  ]));
  $("split-answer").replaceChildren(...r.graphemes.flatMap((g, i) => [
    ...(i ? [el("span", { class: "gap cut static" }, "|")] : []),
    el("span", { class: `tile group ${COLORS[i % COLORS.length]}` }, g),
  ]));
  $("split-next").focus();
}

async function nextWord() {
  s.idx += 1;
  if (s.idx >= s.words.length) return finish();
  showWord();
}

async function finish() {
  $("split-bar").style.width = "100%";
  await savesDone();
  const r = await api("/api/split/finish", {});
  const n = s.words.length;
  showComplete({ title: "Sounds split! ✂️", summary: `You split ${n} words and got ${s.right} completely right.` },
               r.awards, onFinished);
}

$("split-check").onclick = check;
$("split-next").onclick = nextWord;
