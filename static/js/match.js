import { $, api, beginActivity, el, loadSaved, saveProgress, savesDone, show, showComplete } from "./ui.js";

// Sound match: hear a sound, tap every word that has it.
let s = null;
let onFinished = null;
let audio = null;

export async function startMatch(finished) {
  onFinished = finished;
  const saved = await loadSaved("match");
  if (saved) {
    // Carry on after a reload; a round already checked moves on rather than being scored twice.
    beginActivity(saved.tally);
    s = { session: saved.session, rounds: saved.rounds, idx: saved.idx + (saved.answered ? 1 : 0),
          picked: new Set(), checked: false, right: saved.right };
  } else {
    beginActivity();
    const data = await api("/api/match/session", {});
    s = { session: data.session, rounds: data.rounds, idx: 0, picked: new Set(), checked: false, right: 0 };
  }
  show("match");
  if (s.idx >= s.rounds.length) return finish();
  showRound();
}

function save(answered = false) {
  const { session, rounds, idx, right } = s;
  saveProgress("match", { session, rounds, idx, right, answered,
                          label: `${idx + (answered ? 1 : 0)} of ${rounds.length} rounds` });
}

// The bare sound, or the full introduction ("The sound is /s/, as in sun") when it exists.
function play(intro = false) {
  const r = s.rounds[s.idx];
  if (audio) audio.pause();
  audio = new Audio(intro && r.intro_url ? r.intro_url : r.audio_url);
  audio.play().catch(() => {});
}

function showRound() {
  const r = s.rounds[s.idx];
  save();
  s.picked = new Set();
  s.checked = false;
  $("match-bar").style.width = `${(100 * s.idx) / s.rounds.length}%`;
  $("match-hint-text").hidden = true;
  $("match-hint").disabled = !r.hint;
  $("match-feedback").hidden = true;
  $("match-check").hidden = false;
  drawCards();
  play(true);
}

function drawCards(result) {
  const r = s.rounds[s.idx];
  $("match-cards").replaceChildren(...r.cards.map((c) => {
    const verdict = result?.verdicts[c.id];
    const cls = ["word-card"];
    if (!result && s.picked.has(c.id)) cls.push("picked");
    if (verdict) cls.push(verdict);
    const btn = el("button", {
      class: cls.join(" "), "aria-pressed": String(s.picked.has(c.id)), disabled: Boolean(result),
      onclick: () => { s.picked.has(c.id) ? s.picked.delete(c.id) : s.picked.add(c.id); drawCards(); },
    }, ...wordWithSpans(c.word, result?.spans[c.id]));
    if (result && result.lookalikes.includes(c.id)) btn.append(el("span", { class: "card-tag" }, "trick word"));
    if (verdict === "missed") btn.append(el("span", { class: "card-tag" }, "missed"));
    return btn;
  }));
}

// Highlight the letters that spell the sound.
function wordWithSpans(word, spans) {
  if (!spans?.length) return [word];
  const out = [];
  let pos = 0;
  for (const [a, b] of spans) {
    if (a > pos) out.push(word.slice(pos, a));
    out.push(el("mark", {}, word.slice(a, b)));
    pos = b;
  }
  if (pos < word.length) out.push(word.slice(pos));
  return out;
}

async function check() {
  if (s.checked) return;
  s.checked = true;
  const r = await api("/api/match/answer", { session: s.session, round: s.idx, selected: [...s.picked] });
  drawCards(r);
  s.right += r.correct;
  save(true);
  $("match-check").hidden = true;
  $("match-feedback").hidden = false;
  $("match-feedback").className = r.correct ? "feedback good" : "feedback bad";
  $("match-result").textContent = r.correct ? "Yes! You found them all." : "Sorry, not quite. The words with this sound are highlighted.";
  const spellings = [...new Set(r.letters)].join(", ");
  $("match-note").textContent = `This sound can be spelled: ${spellings}`;
  $("match-next").focus();
}

function next() {
  s.idx += 1;
  if (s.idx >= s.rounds.length) return finish();
  showRound();
}

async function finish() {
  $("match-bar").style.width = "100%";
  await savesDone();
  const r = await api("/api/match/finish", {});
  const n = s.rounds.length;
  showComplete({ title: "Great listening! 👂", summary: `You found every word in ${s.right} of ${n} rounds.` },
               r.awards, onFinished);
}

$("match-play").onclick = () => play();
$("match-hint").onclick = () => {
  play(true);
  $("match-hint-text").textContent = `It's the sound in “${s.rounds[s.idx].hint}”.`;
  $("match-hint-text").hidden = false;
};
$("match-check").onclick = check;
$("match-next").onclick = next;
