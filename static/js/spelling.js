import { $, api, beginActivity, celebrate, loadSaved, saveProgress, savesDone, show, showComplete } from "./ui.js";

const RETRY_GAP = 3;   // a missed word comes back this many cards later (once, unscored)
const MAX_COVER_TRIES = 2;

let s = null;          // current session state
let audio = null;
let playToken = 0;     // bumping this cancels an in-progress word/sentence/word sequence
let onFinished = null;

// --- audio ---
function playUrl(url) {
  return new Promise((resolve) => {
    if (audio) audio.pause();
    audio = new Audio(url);
    audio.onended = audio.onerror = resolve;
    audio.play().catch(resolve);
  });
}

function speak(text) {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve();
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.8;
    u.lang = "en-US";
    u.onend = u.onerror = resolve;
    speechSynthesis.speak(u);
  });
}

const playWord = (c) => (c.audio_url ? playUrl(c.audio_url) : speak(c.speak_word));
const playSentence = (c) => (c.sentence_audio_url ? playUrl(c.sentence_audio_url) : c.speak_sentence ? speak(c.speak_sentence) : Promise.resolve());
const hasSentence = (c) => Boolean(c.sentence_audio_url || c.speak_sentence);
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

export async function startSpelling(finished) {
  onFinished = finished;
  const saved = await loadSaved("spelling");
  if (saved) {
    // Carry on after a reload. A card whose answer was already scored moves on (its retry is queued).
    beginActivity(saved.tally);
    s = { ...saved, coverTries: 0, card: null };
    if (s.queue[s.idx]?.recorded) s.idx += 1;
    show("quiz");
    return s.idx >= s.queue.length ? finish(false) : showCard();
  }
  beginActivity();
  const data = await api("/api/session", {});
  if (!data.cards.length) return finish(true);  // only if every word has been learned
  s = { queue: data.cards, idx: 0, total: data.cards.length, firstTry: 0,
        mastered: [], cover: data.cover_and_write, coverTries: 0, card: null };
  show("quiz");
  showCard();
}

function save() {
  const { queue, idx, total, firstTry, mastered, cover } = s;
  const done = queue.slice(0, idx).filter((c) => !c.retry).length;
  saveProgress("spelling", { queue, idx, total, firstTry, mastered, cover, label: `${done} of ${total} words` });
}

function panel(name) {
  for (const id of ["answer-form", "right", "practice-ok", "wrong", "cover-form"]) $(id).hidden = id !== name;
}

function showCard() {
  s.card = s.queue[s.idx];
  s.coverTries = 0;
  const done = s.queue.slice(0, s.idx).filter((c) => !c.retry).length;
  $("bar").style.width = `${(100 * done) / s.total}%`;
  $("rematch-badge").hidden = s.card.kind !== "rematch" || s.card.retry;
  $("play-sentence").hidden = !hasSentence(s.card);
  $("sentence").hidden = !s.card.sentence_blank;
  $("sentence").textContent = s.card.sentence_blank || "";
  $("answer").value = "";
  $("answer").disabled = false;
  save();
  panel("answer-form");
  $("answer").focus();
  autoplay(s.card);
}

// Read the word, use it in a sentence, then read it again (like a spelling test).
async function autoplay(c) {
  const token = ++playToken;
  const steps = hasSentence(c) ? [playWord, playSentence, playWord] : [playWord];
  for (const [i, step] of steps.entries()) {
    if (i) await pause(600);
    if (token !== playToken) return;  // answered or moved on mid-sequence
    await step(c);
  }
}

function nextCard() {
  s.idx += 1;
  if (s.idx >= s.queue.length) return finish(false);
  showCard();
}

async function submitAnswer(e) {
  e.preventDefault();
  const typed = $("answer").value.trim();
  if (!typed) return $("answer").focus();
  $("answer").disabled = true;
  playToken++;
  const c = s.card;
  const r = await api("/api/answer", { id: c.id, typed, practice: Boolean(c.retry) });
  c.typed = typed;

  if (r.correct) {
    if (c.retry) {
      $("practice-word").textContent = r.word;
      panel("practice-ok");
      return $("practice-next").focus();
    }
    s.firstTry += 1;
    $("right-word").textContent = r.word;
    $("case-note").hidden = !r.case_note;
    $("case-note").textContent = r.case_note || "";
    panel("right");
    return;
  }

  if (!c.retry) {
    s.queue.splice(Math.min(s.idx + 1 + RETRY_GAP, s.queue.length), 0, { ...c, retry: true });
    c.recorded = true;   // scored as missed: a reload skips ahead instead of scoring it twice
    save();
  }
  showWrong(r, typed);
}

function showWrong(r, typed) {
  $("letters").replaceChildren(...r.letters.map((l) => {
    const span = document.createElement("span");
    span.textContent = l.ch;
    if (!l.ok) span.className = "miss";
    return span;
  }));
  $("typed").textContent = typed;
  const canCover = s.cover && s.coverTries < MAX_COVER_TRIES;
  $("cover-steps").hidden = !canCover;
  $("wrong-next").hidden = canCover;
  panel("wrong");
  (canCover ? $("cover") : $("wrong-next")).focus();
}

function startCover() {
  $("cover-answer").value = "";
  panel("cover-form");
  $("cover-answer").focus();
}

async function submitCover(e) {
  e.preventDefault();
  const typed = $("cover-answer").value.trim();
  if (!typed) return;
  s.coverTries += 1;
  const r = await api("/api/answer", { id: s.card.id, typed, practice: true });
  if (r.correct) {
    $("practice-word").textContent = r.word;
    panel("practice-ok");
    return $("practice-next").focus();
  }
  showWrong(r, typed);
}

async function choose(choice) {
  const c = s.card;
  for (const b of document.querySelectorAll("[data-choice]")) b.disabled = true;
  try {
    const r = await api("/api/rate", { id: c.id, typed: c.typed, choice });
    if (r.mastered) s.mastered.push($("right-word").textContent);
    celebrate(r.awards);
  } finally {
    for (const b of document.querySelectorAll("[data-choice]")) b.disabled = false;
  }
  nextCard();
}

async function finish(empty) {
  if (empty) {
    return showComplete({ title: "Every word is learned! 🎉",
                          summary: "There are no words left to practise. Ask a grown-up to add more." }, [], onFinished);
  }
  $("bar").style.width = "100%";
  await savesDone();
  const r = await api("/api/activity/done", { activity: "spelling" });
  const n = s.total;
  showComplete({
    summary: `You practised ${n} word${n === 1 ? "" : "s"} and got ${s.firstTry} right on the first try.`,
    list: s.mastered.map((w) => `⭐ You mastered “${w}”!`),
  }, r.awards, onFinished);
}

// --- wiring ---
$("play-word").onclick = () => playWord(s.card);
$("play-sentence").onclick = () => playSentence(s.card);
$("answer-form").onsubmit = submitAnswer;
$("cover").onclick = startCover;
$("cover-form").onsubmit = submitCover;
$("wrong-next").onclick = nextCard;
$("practice-next").onclick = nextCard;
for (const b of document.querySelectorAll("[data-choice]")) b.onclick = () => choose(b.dataset.choice);
document.addEventListener("keydown", (e) => {
  if ($("right").hidden || $("quiz").hidden) return;
  const choice = { 1: "easy", 2: "little_hard", 3: "guessed" }[e.key];
  if (choice) choose(choice);
});
