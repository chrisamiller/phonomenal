"""Spaced-repetition logic: FSRS for intervals, plus our own session mixing and mastery rules.

Time is measured in *practice days*, not calendar days: the counter advances on the
first session of each date the child practises, and stands still on days off. FSRS
sees a synthetic clock (EPOCH + practice_day days), so "come back in 6 days" means
6 practice days, and a vacation creates no backlog.
"""
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import fsrs

CHOICES = ("easy", "little_hard", "guessed")
EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


def clock(day: int) -> datetime:
    return EPOCH + timedelta(days=day)


def due_day(p: dict) -> int:
    return (datetime.fromisoformat(p["card"]["due"]) - EPOCH).days


def new_meta() -> dict:
    return {"practice_day": 0, "last_practice_date": None, "return_day": None}


def advance_day(meta: dict, today: date, settings: dict) -> dict:
    """Start of a session: move to the next practice day if this is a new date."""
    m = dict(meta)
    if m["last_practice_date"] == today.isoformat():
        return m
    last = date.fromisoformat(m["last_practice_date"]) if m["last_practice_date"] else None
    m["practice_day"] += 1
    m["last_practice_date"] = today.isoformat()
    gap = (today - last).days if last else 0
    if gap >= settings["session"]["welcome_back_after_days"]:
        m["return_day"] = m["practice_day"]
    return m


def current_day(meta: dict, today: date) -> int:
    """The practice day a session started now would use (without committing it)."""
    return meta["practice_day"] + (meta["last_practice_date"] != today.isoformat())


def make_scheduler(settings: dict) -> fsrs.Scheduler:
    s = settings["scheduler"]
    # No intraday learning steps: missed words are re-practised within the session by the UI instead (unscored).
    return fsrs.Scheduler(
        desired_retention=s["desired_retention"],
        maximum_interval=s["maximum_interval_days"],
        learning_steps=(),
        relearning_steps=(),
    )


def bucket(progress: dict | None, settings: dict) -> str:
    if not progress:
        return "new"
    d = progress["card"].get("difficulty") or 5.0
    cfg = settings["difficulty"]
    if progress["streak"] == 0:  # missed last time
        return "hard"
    if d < cfg["easy_below"]:
        return "easy"
    if d >= cfg["hard_at_or_above"]:
        return "hard"
    return "medium"


def _interleave(easy: list, medium: list, challenge: list) -> list:
    """Start and finish on an easy word; never put two challenge words back to back if avoidable."""
    out = []
    end = easy.pop() if len(easy) >= 2 else None
    if easy:
        out.append(easy.pop(0))
    while easy or medium or challenge:
        for q in (challenge, easy, medium):
            if q:
                out.append(q.pop(0))
    if end:
        out.append(end)
    return out


def build_session(words: dict, progress: dict, settings: dict, day: int, returning: bool = False, rng=random) -> list[dict]:
    """Pick and order the words for one session. Returns [{id, kind}] where kind is new/review/spot.

    `returning` (first practice day after a long break) holds back new words unless
    there aren't enough reviews to fill the session.
    """
    cfg = settings["session"]
    size = cfg["size"]
    targets = {
        "easy": round(size * cfg["easy_fraction"]),
        "medium": round(size * cfg["medium_fraction"]),
    }
    targets["challenge"] = size - targets["easy"] - targets["medium"]

    due = {"easy": [], "medium": [], "hard": []}
    new, spot = [], []
    spot_after = settings["mastery"]["spot_check_after_days"]
    for wid in words:
        p = progress.get(wid)
        if not p:
            new.append(wid)
        elif p.get("retired"):
            if not p.get("known_on_sight") and day - p["last_review_day"] >= spot_after:
                spot.append(wid)
        elif due_day(p) <= day:
            due[bucket(p, settings)].append(wid)

    # Most overdue first within each bucket.
    for b in due.values():
        b.sort(key=lambda w: due_day(progress[w]))

    new_today = sum(1 for p in progress.values() if p.get("first_review_day") == day)
    new_allowed = max(0, min(cfg["max_new_per_session"], cfg["max_new_per_day"] - new_today))
    top_up = cfg.get("top_up_with_new", True)
    if settings.get("ranking", {}).get("mode") == "level":
        info = pace(words, progress, settings, day)
        new = new_queue(new, words, progress, settings, day, info)
        new_allowed = int(new_allowed * info["factor"])
        top_up = top_up and info["factor"] > 0
    else:
        new = by_tags(new, words, cfg)

    easy = due["easy"][: targets["easy"]]
    medium = due["medium"][: targets["medium"]]
    challenge = due["hard"][: targets["challenge"]]
    new_picked = [] if returning else new[: min(new_allowed, targets["challenge"] - len(challenge))]

    # Fill any shortfall: leftover due words first (they need review), then more new words.
    leftovers = due["easy"][len(easy):] + due["medium"][len(medium):] + due["hard"][len(challenge):]
    chosen = len(easy) + len(medium) + len(challenge) + len(new_picked)
    for wid in leftovers[: max(0, size - chosen)]:
        {"easy": easy, "medium": medium, "hard": challenge}[bucket(progress[wid], settings)].append(wid)
    chosen = len(easy) + len(medium) + len(challenge) + len(new_picked)
    extra_new = new[len(new_picked): len(new_picked) + max(0, min(size - chosen, new_allowed - len(new_picked)))]
    new_picked += extra_new

    # Mastered words make good easy confidence-builders when the session is short.
    chosen = len(easy) + len(medium) + len(challenge) + len(new_picked)
    rng.shuffle(spot)
    spot_picked = spot[: max(0, min(size - chosen, cfg["max_spot_checks"]))]

    # Words missed before come back as rematches.
    # Still short (nothing due, today's new words used up): keep practising with extra new words.
    chosen = len(easy) + len(medium) + len(challenge) + len(new_picked) + len(spot_picked)
    if top_up and chosen < size:
        start = len(new_picked)
        new_picked += new[start: start + size - chosen]

    kinds = {w: "rematch" if progress[w]["lapses"] else "review" for w in easy + medium + challenge}
    kinds.update({w: "new" for w in new_picked})
    kinds.update({w: "spot" for w in spot_picked})
    ordered = _interleave(spot_picked + easy, medium, challenge + new_picked)
    return [{"id": w, "kind": kinds[w]} for w in ordered]


def by_tags(new: list, words: dict, cfg: dict) -> list:
    """New words in the configured tag order, then the order they were added."""
    order = {t: i for i, t in enumerate(cfg.get("new_word_order", []))}
    return sorted(new, key=lambda w: (min((order.get(t, len(order)) for t in words[w].get("tags", [])), default=len(order)),
                                      words[w].get("added", "")))


def _ranked(w: dict) -> bool:
    return "order" in (w.get("rank") or {})


def _priority(w: dict, r: dict) -> bool:
    return bool(set(w.get("tags", [])) & set(r.get("priority_tags", [])))


def _skipped(w: dict, r: dict) -> bool:
    """Below [ranking] start_level: too easy to introduce."""
    return w["rank"]["level"] < r.get("start_level", 1)


def pace(words: dict, progress: dict, settings: dict, day: int) -> dict:
    """How fast to bring in new words: her current level, and a factor (1, 0.5 or 0) with the reason."""
    r = settings["ranking"]
    recent = [p for p in progress.values() if p.get("last_review_day") is not None
              and day - p["last_review_day"] < r["pace_window_days"] and not p.get("retired")]
    accuracy = sum(p["streak"] > 0 for p in recent) / len(recent) if recent else None
    pending = [w["rank"]["level"] for wid, w in words.items()
               if wid not in progress and _ranked(w) and not _priority(w, r) and not _skipped(w, r)]
    level = min(pending) if pending else None
    prev = [progress[wid] for wid, w in words.items()
            if wid in progress and level and level - 1 >= r.get("start_level", 1)
            and (w.get("rank") or {}).get("level") == level - 1]                 # a skipped level doesn't hold the next back
    ready = sum(p["streak"] > 0 or bool(p.get("retired")) for p in prev) / len(prev) if len(prev) >= 5 else None
    factor, reason = 1.0, None
    if accuracy is not None and len(recent) >= r["pace_min_reviews"]:
        if accuracy < r["pace_stop_below"]:
            factor, reason = 0.0, f"No new words for now: {accuracy:.0%} of recent words right on the last try. Reviews first."
        elif accuracy < r["pace_slow_below"]:
            factor, reason = 0.5, f"Fewer new words: {accuracy:.0%} of recent words right on the last try."
    if factor and ready is not None and ready < r["level_ready"]:
        factor = min(factor, 0.5)
        reason = reason or (f"Level {level} is opening slowly: level {level - 1} words are {ready:.0%} right "
                            f"(needs {r['level_ready']:.0%}).")
    return {"level": level, "factor": factor, "reason": reason, "accuracy": accuracy, "recent": len(recent),
            "previous_level_ready": ready, "level_open": factor >= 1}


def new_queue(new: list, words: dict, progress: dict, settings: dict, day: int, info: dict) -> list:
    """New words in introduction order for this session (see app/ranking.py and [ranking] settings)."""
    r = settings["ranking"]
    ranked = sorted((w for w in new if _ranked(words[w])), key=lambda w: words[w]["rank"]["order"])
    unranked = by_tags([w for w in new if not _ranked(words[w])], words, settings["session"])
    prio = [w for w in ranked if _priority(words[w], r)]
    main = [w for w in ranked if not _priority(words[w], r) and not _skipped(words[w], r)]
    level = info["level"]
    current = [w for w in main if words[w]["rank"]["level"] == level]
    later = [w for w in main if words[w]["rank"]["level"] != level]
    # A preview word from a harder level every few slots, once the current level is solid. Previews rotate
    # through levels above the current one, up to preview_max_level, easiest word of each level first.
    top = max(r.get("preview_max_level", 0), (level or 0) + 1)
    preview = defaultdict(list)
    for w in later:
        if level is not None and level < words[w]["rank"]["level"] <= top:
            preview[words[w]["rank"]["level"]].append(w)
    rotation = [preview[lv] for lv in sorted(preview)]
    every = round(1 / r["preview_fraction"]) if r["preview_fraction"] and info["level_open"] else 0
    queue = prio[: r["priority_per_session"]]
    turn = 0
    while current or later:
        rotation = [ws for ws in rotation if ws]
        if every and rotation and current and len(queue) % every == every - 1:
            w = rotation[turn % len(rotation)].pop(0)
            turn += 1
            later.remove(w)
        elif current:
            w = current.pop(0)
        else:
            w = later.pop(0)
            for ws in rotation:
                if w in ws:
                    ws.remove(w)
        queue.append(w)
    queue += prio[r["priority_per_session"]:] + unranked

    # Per-session limits: one heart word; never a homophone of a word introduced recently (or this session).
    recent = {wid for wid, p in progress.items() if day - p.get("first_review_day", -999) < r["homophone_gap_days"]}
    out, deferred, hearts = [], [], 0
    for w in queue:
        rk = words[w].get("rank") or {}
        if (rk.get("heart") and hearts >= r["max_heart_per_session"]) or set(rk.get("homophones", [])) & (recent | set(out)):
            deferred.append(w)
            continue
        out.append(w)
        hearts += bool(rk.get("heart"))
    return out + deferred


def record(progress: dict | None, word_id: str, correct: bool, choice: str | None, settings: dict,
           day: int, now: datetime) -> tuple[dict, str]:
    """Apply one scored answer on practice day `day`. Returns (new progress, FSRS rating name)."""
    if correct:
        if choice not in CHOICES:
            raise ValueError(f"choice must be one of {CHOICES}")
        rating_name = settings["ratings"][choice]
    else:
        rating_name = "Again"

    p = dict(progress) if progress else {
        "id": word_id, "card": fsrs.Card().to_dict(), "reps": 0, "lapses": 0, "streak": 0,
        "retired": False, "retired_at": None, "first_review_day": day, "last_review_day": None,
        "last_review": None,
    }
    card, _ = make_scheduler(settings).review_card(fsrs.Card.from_dict(p["card"]), fsrs.Rating[rating_name], clock(day))
    p["card"] = card.to_dict()
    p["max_difficulty"] = max(p.get("max_difficulty", 0), card.difficulty)
    p["reps"] += 1
    p["last_review_day"] = day
    p["last_review"] = now.isoformat()  # real time, for the grown-ups' view
    if correct:
        p["streak"] += 1
    else:
        p["streak"] = 0
        p["lapses"] += 1
        p["retired"], p["retired_at"] = False, None

    m = settings["mastery"]
    if correct and not p["retired"] and p["streak"] >= m["min_streak"] and card.stability >= m["min_stability_days"]:
        p["retired"], p["retired_at"] = True, now.isoformat()
    elif progress is None and correct and choice == "easy" and m.get("easy_on_first_sight", True):
        # Spelled right the very first time and called easy: she already knows it. Mastered, and never shown again.
        p["retired"], p["retired_at"], p["known_on_sight"] = True, now.isoformat(), True
    return p, rating_name


def status(p: dict | None, day: int) -> str:
    if not p:
        return "new"
    if p.get("retired"):
        return "mastered"
    return "due" if due_day(p) <= day else "learning"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    return datetime.now().astimezone().date()
