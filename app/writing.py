"""Writing practice: one prompt a day, free writing, stored for the grown-ups to review."""
import csv
import hashlib
import io
import random
import re
from datetime import timedelta
from pathlib import Path

from . import economy
from .scheduler import today, utcnow

PROMPTS = "prompts"
RESPONSES = "responses"
ASSIGNED = "prompt_days"   # which prompt was shown on which date


def parse_prompts(path: Path) -> list[dict]:
    """prompts.txt: one prompt per line; '# Heading' lines set the category."""
    out, category = [], "general"
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading and len(heading) < 40 and not heading.endswith("."):
                category = heading.lower()
            continue
        pid = hashlib.sha1(line.encode()).hexdigest()[:10]
        out.append({"id": pid, "text": line, "category": category, "status": "approved"})
    return out


def import_prompts(store, path: Path) -> tuple[int, int]:
    """Add new prompts and retire ones no longer in the file (kept for old responses)."""
    incoming = {p["id"]: p for p in parse_prompts(path)}
    existing = store.docs(PROMPTS)
    for pid, p in existing.items():
        if pid not in incoming and p["status"] == "approved":
            p["status"] = "removed"
            incoming[pid] = p
    for pid, p in incoming.items():
        if pid in existing and p["status"] == "approved":
            p["added"] = existing[pid].get("added")
        p.setdefault("added", utcnow().isoformat())
    store.put_docs(PROMPTS, list(incoming.values()))
    new = sum(1 for pid in incoming if pid not in existing)
    return new, sum(1 for p in incoming.values() if p["status"] == "approved")


def todays_prompt(store, settings: dict, rng=random) -> dict | None:
    d = today()
    assigned = store.docs(ASSIGNED)
    if d.isoformat() in assigned:
        pid = assigned[d.isoformat()]["prompt_id"]
        return store.get_doc(PROMPTS, pid)
    prompts = [p for p in store.docs(PROMPTS).values() if p["status"] == "approved"]
    if not prompts:
        return None
    cutoff = (d - timedelta(days=settings["writing"]["no_repeat_days"])).isoformat()
    recent = {a["prompt_id"] for a in assigned.values() if a["id"] >= cutoff}
    pool = [p for p in prompts if p["id"] not in recent] or prompts
    p = rng.choice(sorted(pool, key=lambda p: p["id"]))
    store.put_docs(ASSIGNED, [{"id": d.isoformat(), "prompt_id": p["id"]}])
    return p


def count_sentences(text: str) -> int:
    parts = [s for s in re.split(r"[.!?]+(?:\s|$)", text.strip()) if re.search(r"[A-Za-z]", s)]
    return len(parts)


def count_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’]+", text))


def todays_response(store) -> dict | None:
    d = today().isoformat()
    return next((r for r in reversed(store.records(RESPONSES)) if r["date"] == d), None)


def submit(store, prompt: dict, text: str, started: str | None) -> dict:
    d = today()
    rec = {
        "id": hashlib.sha1(f"{utcnow().isoformat()}{text}".encode()).hexdigest()[:12],
        "ts": utcnow().isoformat(), "started": started, "date": d.isoformat(), "iso_week": economy.iso_week(d),
        "prompt_id": prompt["id"], "prompt": prompt["text"], "category": prompt["category"],
        "text": text, "words": count_words(text), "sentences": count_sentences(text),
    }
    store.append(RESPONSES, [rec])
    return rec


def export_csv(store) -> str:
    buf = io.StringIO()
    cols = ["date", "ts", "started", "category", "prompt", "words", "sentences", "text"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(store.records(RESPONSES))
    return buf.getvalue()
