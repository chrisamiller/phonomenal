"""Achievements: every rule is a threshold on a stat computed from stored data.

Stats are recomputed from scratch on each check (the data is small), so
achievements are also retroactive: adding a new one awards it if already earned.
Earned achievements are never removed. `repeatable` achievements are earned again each
time their counter goes up (e.g. every new 3-day streak).
"""
import re
import tomllib
from collections import defaultdict
from datetime import date, datetime

from . import economy, missions
from .config import ROOT

EARNED = "achievements"
PATH = ROOT / "achievements.toml"

# Homophone sets for Homophone Hero (only sets fully present in the word list count).
HOMOPHONES = [
    ["their", "there", "they’re"], ["to", "too", "two"], ["hear", "here"], ["for", "four"],
    ["no", "know"], ["right", "write"], ["by", "buy"], ["be", "bee"], ["sail", "sale"],
    ["steal", "steel"], ["weak", "week"], ["wear", "where"], ["whole", "hole"], ["knight", "night"],
    ["knot", "not"], ["son", "sun"], ["some", "sum"], ["peace", "piece"], ["wait", "weight"],
    ["bare", "bear"], ["ate", "eight"], ["mail", "male"], ["cent", "sent"], ["cell", "sell"],
    ["site", "sight"], ["scene", "seen"],
]


def load() -> list[dict]:
    with open(PATH, "rb") as f:
        return tomllib.load(f)["achievement"]


def _local(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone()


def compute_stats(store, settings: dict) -> dict:
    s = defaultdict(int)
    words = store.all_words()
    progress = store.all_progress()
    reviews = store.reviews()
    ledger = store.records(economy.LEDGER)
    counters = (store.get_meta() or {}).get("counters", {})

    # --- missions / consistency ---
    done = missions.completed(store)
    goal = settings["mission"]["weekly_goal"]
    per_week = defaultdict(int)
    for m in done:
        per_week[m["iso_week"]] += 1
        t = _local(m["completed_at"])
        s["weekend_missions"] += missions.is_weekend(m["id"])
        s["early_missions"] += t.hour < 8
        s["late_missions"] += t.hour >= 19
        s["comeback_missions"] += bool(m.get("returning"))
        all_acts = ["spelling"] + settings["mission"]["extras"]
        s["all_activities_days"] += all(a in m["done"] for a in all_acts)
    s["missions_completed"] = len(done)
    goal_weeks = sorted(w for w, n in per_week.items() if n >= goal)
    s["weekly_goals_met"] = len(goal_weeks)
    s["perfect_weeks"] = sum(n >= 7 for n in per_week.values())
    s["goal_week_streak"] = _longest_consecutive_weeks(goal_weeks)
    runs = _day_runs([m["id"] for m in done])
    for n in STREAK_LENGTHS:
        s[f"streaks_{n}"] = sum(1 for r in runs if r >= n)
    if done:
        first = date.fromisoformat(done[0]["id"])
        anniv = first.replace(year=first.year + 1) if not (first.month == 2 and first.day == 29) else first.replace(year=first.year + 1, day=28)
        s["anniversary"] = int(any(m["id"] == anniv.isoformat() for m in done))

    # --- spelling ---
    # "quiet" masteries (earlier words marked mastered after the fact) don't count toward achievements.
    earned = [p for p in progress.values() if p.get("retired") and not p.get("quiet")]
    s["words_mastered"] = len(earned)
    s["brink_words"] = sum(1 for p in earned if p.get("max_difficulty", 0) >= 8)
    s["rematches_won"] = sum(1 for r in ledger if r["source"] == "rematch")
    scored = [r for r in reviews if "correct" in r]
    run = best = 0
    correct_words = set()
    week_correct = defaultdict(set)
    for r in scored:
        run = run + 1 if r["correct"] else 0
        best = max(best, run)
        if r["correct"]:
            w = words.get(r["id"], {}).get("word", "")
            correct_words.add(w)
            week_correct[economy.iso_week(_local(r["ts"]).date())].add(w)
            s["never_give_up"] += r.get("lapses_before", 0) >= 3
    s["first_try_streak"] = best
    s["palindromes"] = sum(1 for w in correct_words if len(w) >= 3 and w.lower() == w.lower()[::-1])
    s["alphabet_letters"] = len({w[0].lower() for w in correct_words if w and w[0].isalpha()})
    s["capitals_spelled"] = sum(1 for w in correct_words if w[:1].isupper() and len(w) > 1)
    contractions = {w["word"] for w in words.values() if "'" in w["word"] or "’" in w["word"]}
    s["contractions_complete"] = int(bool(contractions) and contractions <= correct_words)
    vocab = {w["word"] for w in words.values()}
    sets = [hs for hs in HOMOPHONES if set(hs) <= vocab]
    s["homophone_set_weeks"] = sum(1 for got in week_correct.values() for hs in sets if set(hs) <= got)

    # --- writing ---
    responses = store.records("responses")
    s["writing_responses"] = len(responses)
    s["words_written"] = sum(r["words"] for r in responses)
    s["max_response_sentences"] = max((r["sentences"] for r in responses), default=0)
    days_by_week = defaultdict(set)
    long_words = set()
    for r in responses:
        days_by_week[r["iso_week"]].add(r["date"])
        long_words |= {w.lower() for w in re.findall(r"[A-Za-z']+", r["text"]) if len(w) > 6}
    s["writing_week_days"] = max((len(v) for v in days_by_week.values()), default=0)
    s["long_words_used"] = len(long_words)
    categories = {p["category"] for p in store.docs("prompts").values() if p.get("status") == "approved"}
    s["prompt_categories_complete"] = int(bool(categories) and categories <= {r["category"] for r in responses})

    # --- sound splitting ---
    split = store.records("split_results")
    s["words_split"] = len(split)
    sessions = defaultdict(list)
    for r in split:
        if r.get("vowel_team"):
            sessions[r["session"]].append(r["split_ok"])
    s["vowel_team_perfect_sessions"] = sum(1 for v in sessions.values() if len(v) >= 3 and all(v))

    # --- sound match ---
    from . import match
    s.update(match.stats(store))

    # --- aquarium / economy ---
    from . import aquarium
    s.update(aquarium.stats(store))
    running = peak = 0
    for r in ledger:
        running += r["amount"]
        peak = max(peak, running)
        if r["source"] == "purchase":
            s["max_purchase"] = max(s["max_purchase"], -r["amount"])
    s["max_balance"] = peak
    s["rearrangements"] = counters.get("rearrangements", 0)
    s["fish_whisperer"] = counters.get("fish_whisperer", 0)
    return dict(s)


STREAK_LENGTHS = (3, 5, 7, 14, 30)


def _day_runs(days: list[str]) -> list[int]:
    """Lengths of runs of consecutive calendar days."""
    runs, prev = [], None
    for d in sorted(set(days)):
        cur = date.fromisoformat(d)
        if prev and (cur - prev).days == 1:
            runs[-1] += 1
        else:
            runs.append(1)
        prev = cur
    return runs


def _longest_consecutive_weeks(weeks: list[str]) -> int:
    best = run = 0
    prev = None
    for w in weeks:
        y, n = map(int, w.split("-W"))
        monday = date.fromisocalendar(y, n, 1)
        run = run + 1 if prev and (monday - prev).days == 7 else 1
        best, prev = max(best, run), monday
    return best


def _thresholds(rule: dict) -> list[int]:
    return rule["tiers"] if "tiers" in rule else [rule["at_least"]]


def check(store, settings: dict) -> list[dict]:
    """Award any newly earned achievements (and their credits). Returns popup-ready awards."""
    awards = []
    for _ in range(3):  # achievement credits can unlock balance-based achievements
        earned = store.docs(EARNED)
        stats = compute_stats(store, settings)
        new = []
        for a in load():
            if a.get("repeatable"):
                times = sum(1 for e in earned.values() if e["achievement"] == a["id"])
                for k in range(times + 1, stats.get(a["rule"]["counter"], 0) + 1):
                    new.append({"id": f"{a['id']}#{k}", "achievement": a["id"], "tier": None, "times": k,
                                "name": a["name"], "description": a["description"], "credits": a.get("credits", 0),
                                "ts": datetime.now().astimezone().isoformat()})
                continue
            tiers = _thresholds(a["rule"])
            for i, t in enumerate(tiers):
                key = a["id"] if len(tiers) == 1 else f"{a['id']}@{t}"
                if key in earned or stats.get(a["rule"]["counter"], 0) < t:
                    continue
                credits = a.get("credits", 0)
                new.append({"id": key, "achievement": a["id"], "tier": t if len(tiers) > 1 else None,
                            "name": a["name"], "description": a["description"], "credits": credits,
                            "ts": datetime.now().astimezone().isoformat()})
        if not new:
            break
        store.put_docs(EARNED, new)
        for n in new:
            awards.append({"kind": "achievement", **n})
            if n["credits"]:
                economy.award(store, "achievement", n["credits"], n["id"])
    return awards


def shelf(store) -> dict:
    """Earned achievements only (most recent first), plus how many are still to earn."""
    earned = list(store.docs(EARNED).values())
    today = datetime.now().astimezone().date()
    items, unearned = [], 0
    for a in load():
        mine = [e for e in earned if e["achievement"] == a["id"]]
        if not a.get("repeatable"):  # ignore awards from thresholds that have since been changed
            tiers = _thresholds(a["rule"])
            valid = {a["id"]} if len(tiers) == 1 else {f"{a['id']}@{t}" for t in tiers}
            mine = [e for e in mine if e["id"] in valid]
        if not mine:
            unearned += 1
            continue
        last = max(mine, key=lambda e: e["ts"])
        tiers = None if a.get("repeatable") else _thresholds(a["rule"])
        items.append({
            "id": a["id"], "name": a["name"], "description": a["description"], "hidden": a.get("hidden", False),
            "times": len(mine) if a.get("repeatable") else None,
            "tiers": tiers if tiers and len(tiers) > 1 else None,
            "earned_tiers": sorted(e["tier"] for e in mine if e.get("tier")),
            "last_earned": last["ts"],
            "today": any(datetime.fromisoformat(e["ts"]).astimezone().date() == today for e in mine),
        })
    items.sort(key=lambda i: i["last_earned"], reverse=True)
    return {"items": items, "unearned": unearned}
