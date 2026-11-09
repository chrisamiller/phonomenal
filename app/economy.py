"""Credits: an append-only ledger. The balance and every report are computed from it."""
from collections import defaultdict
from datetime import date, datetime

from .scheduler import today, utcnow

LEDGER = "ledger"


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def award(store, source: str, amount: int, detail: str = "") -> dict:
    """Record credits earned (positive) or spent (negative). Returns a popup-ready award."""
    now, d = utcnow(), today()
    store.append(LEDGER, [{
        "ts": now.isoformat(), "date": d.isoformat(), "iso_week": iso_week(d),
        "practice_day": (store.get_meta() or {}).get("practice_day", 0),
        "amount": amount, "source": source, "detail": detail,
    }])
    return {"kind": "credits", "amount": amount, "source": source, "detail": detail}


def balance(store) -> int:
    return sum(r["amount"] for r in store.records(LEDGER))


def report(store, prices: dict[str, int] | None = None, owned: set[str] | None = None) -> dict:
    """Earning/spending rates for tuning the economy."""
    ledger = store.records(LEDGER)
    weeks = defaultdict(lambda: {"earned": 0, "spent": 0, "days": set()})
    by_source = defaultdict(int)
    days = set()
    running, history, purchases, last_purchase_ts = 0, [], [], None
    for r in ledger:
        w = weeks[r["iso_week"]]
        if r["amount"] >= 0:
            w["earned"] += r["amount"]
            by_source[r["source"]] += r["amount"]
            w["days"].add(r["date"])
            days.add(r["date"])
        else:
            w["spent"] -= r["amount"]
        running += r["amount"]
        history.append({"ts": r["ts"], "balance": running})
        if r["source"] == "purchase":
            start = datetime.fromisoformat(last_purchase_ts or ledger[0]["ts"])
            purchases.append({"date": r["date"], "item": r["detail"], "price": -r["amount"],
                              "days_saving": (datetime.fromisoformat(r["ts"]) - start).days})
            last_purchase_ts = r["ts"]

    earned = sum(by_source.values())
    per_day = earned / len(days) if days else 0
    recent = sorted(weeks)[-4:]
    per_week = sum(weeks[w]["earned"] for w in recent) / len(recent) if recent else 0
    target = None
    if prices:
        unowned = {k: v for k, v in prices.items() if k not in (owned or set())}
        if unowned:
            item, price = max(unowned.items(), key=lambda kv: kv[1])
            short = max(0, price - running)
            target = {"item": item, "price": price,
                      "weeks_to_afford": round(short / per_week, 1) if per_week else None}
    return {
        "balance": running,
        "earned_total": earned,
        "spent_total": sum(w["spent"] for w in weeks.values()),
        "avg_per_practice_day": round(per_day, 1),
        "avg_per_week_recent": round(per_week, 1),
        "by_source": dict(sorted(by_source.items(), key=lambda kv: -kv[1])),
        "weeks": [{"week": k, "earned": v["earned"], "spent": v["spent"], "practice_days": len(v["days"])}
                  for k, v in sorted(weeks.items())],
        "purchases": purchases,
        "balance_history": history,
        "most_expensive_unowned": target,
    }
