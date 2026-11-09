"""Daily missions: spelling plus 1-2 chosen activities, a weekly goal, and the credits they earn."""
from datetime import date, timedelta

from . import economy
from .scheduler import today, utcnow

MISSIONS = "missions"
ACTIVITIES = ("spelling", "writing", "split", "match")


def get_today(store) -> dict:
    d = today()
    m = store.get_doc(MISSIONS, d.isoformat())
    if m:
        return m
    meta = store.get_meta() or {}
    return {"id": d.isoformat(), "iso_week": economy.iso_week(d), "chosen": None, "done": {},
            "completed_at": None, "returning": False, "practice_day": meta.get("practice_day")}


def choose(store, settings: dict, extras: list[str]) -> dict:
    cfg = settings["mission"]
    extras = [e for e in dict.fromkeys(extras) if e in cfg["extras"]]
    if not cfg["min_extras"] <= len(extras) <= cfg["max_extras"]:
        raise ValueError(f"choose {cfg['min_extras']}-{cfg['max_extras']} of {cfg['extras']}")
    m = get_today(store)
    m["chosen"] = ["spelling"] + extras
    store.put_docs(MISSIONS, [m])
    return m


def mark_returning(store) -> None:
    """Called when a practice day starts after a long break (for the Comeback Kid achievement)."""
    m = get_today(store)
    m["returning"] = True
    store.put_docs(MISSIONS, [m])


def complete_activity(store, settings: dict, activity: str) -> list[dict]:
    """Record a finished activity; returns credit awards for any newly earned rewards."""
    if activity not in ACTIVITIES:
        raise ValueError(activity)
    credits = settings["credits"]
    m = get_today(store)
    awards = []
    if activity not in m["done"]:
        m["done"][activity] = utcnow().isoformat()
        awards.append(economy.award(store, "activity", credits["activity"], activity))
    else:
        amount = repeat_credits_available(store, settings)
        if amount:
            awards.append(economy.award(store, "activity_repeat", amount, activity))
    chosen = m["chosen"] or ["spelling"]
    if not m["completed_at"] and m["chosen"] and all(a in m["done"] for a in chosen):
        m["completed_at"] = utcnow().isoformat()
        awards.append(economy.award(store, "mission", credits["mission"], m["id"]))
        store.put_docs(MISSIONS, [m])
        week = week_summary(store, settings)
        if week["count"] == settings["mission"]["weekly_goal"]:
            awards.append(economy.award(store, "weekly_goal", credits["weekly_goal"], m["iso_week"]))
    store.put_docs(MISSIONS, [m])
    return awards


def repeat_credits_available(store, settings: dict) -> int:
    """Credits the next bonus replay would earn today (respecting the daily cap)."""
    c = settings["credits"]
    cap = c.get("repeat_daily_cap", 0)
    if not cap:
        return c["activity_repeat"]
    d = today().isoformat()
    so_far = sum(r["amount"] for r in store.records(economy.LEDGER) if r["source"] == "activity_repeat" and r["date"] == d)
    return max(0, min(c["activity_repeat"], cap - so_far))


def week_summary(store, settings: dict) -> dict:
    d = today()
    monday = d - timedelta(days=d.weekday())
    missions = store.docs(MISSIONS)
    days = []
    for i in range(7):
        day = monday + timedelta(days=i)
        m = missions.get(day.isoformat())
        days.append({"date": day.isoformat(), "weekday": day.strftime("%a"),
                     "done": bool(m and m["completed_at"]), "today": day == d})
    count = sum(x["done"] for x in days)
    goal = settings["mission"]["weekly_goal"]
    return {"days": days, "count": count, "goal": goal, "met": count >= goal}


def completed(store) -> list[dict]:
    return sorted((m for m in store.docs(MISSIONS).values() if m["completed_at"]), key=lambda m: m["id"])


def is_weekend(day: str) -> bool:
    return date.fromisoformat(day).weekday() >= 5
