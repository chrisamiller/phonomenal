import asyncio
import re
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import achievements, aquarium, auth, economy, match, missions, phonics, scheduler, writing
from .config import DATA_DIR, ROOT, load_settings
from .grading import grade
from .store import open_store

store = open_store()
app = FastAPI(title="Phonomenal")
STATIC = ROOT / "static"


def _blank(sentence: str, word: str) -> str:
    return re.sub(rf"\b{re.escape(word)}\b", "_____", sentence, flags=re.IGNORECASE)


def _card(w: dict, kind: str) -> dict:
    return {
        "id": w["id"],
        "kind": kind,
        "audio_url": store.media_url(w["audio"]),
        "sentence_audio_url": store.media_url(w["sentence_audio"]),
        "sentence_blank": _blank(w["sentence"], w["word"]) if w["sentence"] else None,
        # Used only for the browser-voice fallback when a clip is missing.
        "speak_word": None if w["audio"] else w["word"],
        "speak_sentence": w["sentence"] if w["sentence"] and not w["sentence_audio"] else None,
    }


def _word(word_id: str) -> dict:
    w = store.get_word(word_id)
    if not w:
        raise HTTPException(404, "unknown word")
    return w


def _meta() -> dict:
    return store.get_meta() or scheduler.new_meta()


def _bump(counter: str, value: int | None = None) -> None:
    meta = _meta()
    c = meta.setdefault("counters", {})
    c[counter] = value if value is not None else c.get(counter, 0) + 1
    store.put_meta(meta)


def _with_achievements(awards: list[dict], settings: dict) -> list[dict]:
    return awards + achievements.check(store, settings)


def _bad(e: ValueError):
    raise HTTPException(400, str(e))


# ---------------------------------------------------------------- saved progress
# Each activity's in-progress state, so a reload carries on where she left off. Kept for the day it was
# saved (server local time, i.e. the family's time zone); after midnight it's ignored and she starts fresh.
SAVED = "saved_progress"
ACTIVITIES = ("spelling", "writing", "split", "match")


def _saved(activity: str) -> dict | None:
    d = store.get_doc(SAVED, activity)
    return d["state"] if d and d.get("state") and d.get("date") == scheduler.today().isoformat() else None


def _clear_saved(activity: str) -> None:
    store.put_docs(SAVED, [{"id": activity, "date": None, "state": None}])


class Saved(BaseModel):
    state: dict | None


@app.get("/api/saved/{activity}")
def get_saved(activity: str):
    if activity not in ACTIVITIES:
        raise HTTPException(404, "unknown activity")
    return {"state": _saved(activity)}


@app.post("/api/saved/{activity}")
def put_saved(activity: str, s: Saved):
    if activity not in ACTIVITIES:
        raise HTTPException(404, "unknown activity")
    store.put_docs(SAVED, [{"id": activity, "date": scheduler.today().isoformat(), "state": s.state}])
    return {"ok": True}


# ---------------------------------------------------------------- home / mission

@app.get("/api/balance")
def balance():
    return {"balance": economy.balance(store)}


@app.get("/api/home")
def home():
    settings = load_settings()
    m = missions.get_today(store)
    extras = settings["mission"]["extras"]
    return {
        "mission": m,
        "week": missions.week_summary(store, settings),
        "balance": economy.balance(store),
        "extras": extras,
        "min_extras": settings["mission"]["min_extras"],
        "max_extras": settings["mission"]["max_extras"],
        "has_prompts": any(p["status"] == "approved" for p in store.docs(writing.PROMPTS).values()),
        "repeat_credits": missions.repeat_credits_available(store, settings),
        "saved": {a: st.get("label") or "in progress" for a in ACTIVITIES if (st := _saved(a))},
    }


class Choose(BaseModel):
    extras: list[str]


@app.post("/api/mission/choose")
def mission_choose(c: Choose):
    try:
        return missions.choose(store, load_settings(), c.extras)
    except ValueError as e:
        _bad(e)


class Done(BaseModel):
    activity: str


@app.post("/api/activity/done")
def activity_done(d: Done):
    """Spelling reports completion here; writing and splitting complete via their own endpoints."""
    if d.activity != "spelling":
        raise HTTPException(400, "only spelling completes this way")
    settings = load_settings()
    _clear_saved("spelling")
    return {"awards": _with_achievements(missions.complete_activity(store, settings, "spelling"), settings)}


@app.get("/api/trophies")
def trophies():
    return achievements.shelf(store)


# ---------------------------------------------------------------- spelling

@app.get("/api/status")
def get_status():
    day = scheduler.current_day(_meta(), scheduler.today())
    progress = store.all_progress()
    counts = {"new": 0, "learning": 0, "due": 0, "mastered": 0}
    for wid in store.all_words():
        counts[scheduler.status(progress.get(wid), day)] += 1
    return counts


@app.post("/api/session")
def new_session():
    settings = load_settings()
    meta = scheduler.advance_day(_meta(), scheduler.today(), settings)
    store.put_meta(meta)
    day = meta["practice_day"]
    returning = meta["return_day"] == day
    if returning:
        missions.mark_returning(store)
    words = store.all_words()
    picks = scheduler.build_session(words, store.all_progress(), settings, day, returning=returning)
    return {
        "cards": [_card(words[p["id"]], p["kind"]) for p in picks],
        "cover_and_write": settings["practice"]["cover_and_write"],
    }


class Answer(BaseModel):
    id: str
    typed: str
    practice: bool = False  # retries within a session and cover-and-write are not scored


class Rate(BaseModel):
    id: str
    typed: str
    choice: str


def _review(word_id: str, old: dict | None, p: dict, typed: str, correct: bool, rating: str, day: int) -> None:
    store.save_review(p, {"id": word_id, "ts": scheduler.utcnow().isoformat(), "day": day, "typed": typed,
                          "correct": correct, "rating": rating, "lapses_before": old["lapses"] if old else 0,
                          "spot_check": bool(old and old.get("retired"))})


@app.post("/api/answer")
def answer(a: Answer):
    settings = load_settings()
    w = _word(a.id)
    result = grade(a.typed, w["word"], settings["grading"]["strict_case"])
    result["recorded"] = False
    if not result["correct"] and not a.practice:
        day = _meta()["practice_day"]
        old = store.get_progress(a.id)
        p, rating = scheduler.record(old, a.id, False, None, settings, day, scheduler.utcnow())
        _review(a.id, old, p, a.typed, False, rating, day)
        result["recorded"] = True
    return result


@app.post("/api/rate")
def rate(r: Rate):
    settings = load_settings()
    w = _word(r.id)
    if not grade(r.typed, w["word"], settings["grading"]["strict_case"])["correct"]:
        raise HTTPException(400, "answer was not correct")
    if r.choice not in scheduler.CHOICES:
        raise HTTPException(400, f"choice must be one of {scheduler.CHOICES}")
    day = _meta()["practice_day"]
    old = store.get_progress(r.id)
    p, rating = scheduler.record(old, r.id, True, r.choice, settings, day, scheduler.utcnow())
    _review(r.id, old, p, r.typed, True, rating, day)
    mastered = p["retired"] and not (old and old.get("retired"))
    awards = []
    if old and old["lapses"] and not old.get("retired"):
        awards.append(economy.award(store, "rematch", settings["credits"]["rematch"], w["word"]))
    # /api/rate is only reached by a scored answer that was right first time (retries are practice).
    awards.append(economy.award(store, "correct_word", settings["credits"]["correct_word"], w["word"]))
    return {"due_in": scheduler.due_day(p) - day, "mastered": mastered,
            "awards": _with_achievements(awards, settings)}


# ---------------------------------------------------------------- writing

@app.get("/api/writing/today")
def writing_today():
    settings = load_settings()
    p = writing.todays_prompt(store, settings)
    if not p:
        raise HTTPException(404, "no prompts loaded")
    done = writing.todays_response(store)
    return {"prompt": {"id": p["id"], "text": p["text"]}, "done": bool(done),
            "min_sentences": settings["writing"]["min_sentences"], "min_words": settings["writing"]["min_words"]}


class Writing(BaseModel):
    text: str
    started: str | None = None


@app.post("/api/writing/submit")
def writing_submit(wr: Writing):
    settings = load_settings()
    p = writing.todays_prompt(store, settings)
    cfg = settings["writing"]
    text = wr.text.strip()
    if writing.count_sentences(text) < cfg["min_sentences"] and writing.count_words(text) < cfg["min_words"]:
        raise HTTPException(400, f"write at least {cfg['min_sentences']} sentences")
    rec = writing.submit(store, p, text, wr.started)
    _clear_saved("writing")
    awards = missions.complete_activity(store, settings, "writing")
    return {"words": rec["words"], "sentences": rec["sentences"], "awards": _with_achievements(awards, settings)}


@app.get("/api/export/writing")
def export_writing():
    return Response(writing.export_csv(store), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=writing-{scheduler.today()}.csv"})


# ---------------------------------------------------------------- sound splitting

@app.post("/api/split/session")
def split_session():
    settings = load_settings()
    words = phonics.pick_session(store, settings["split"]["words_per_session"])
    return {"session": uuid.uuid4().hex[:10], "words": words}


class SplitAnswer(BaseModel):
    session: str
    id: str
    count: int
    split: list[int]


@app.post("/api/split/answer")
def split_answer(a: SplitAnswer):
    w = _word(a.id)
    if (w.get("phonics") or {}).get("status") != "ok":
        raise HTTPException(400, "word not available for splitting")
    r = phonics.check(w, a.count, a.split)
    d = scheduler.today()
    store.append("split_results", [{
        "ts": scheduler.utcnow().isoformat(), "date": d.isoformat(), "session": a.session,
        "word_id": a.id, "word": w["word"], "count_answer": a.count, "count_ok": r["count_ok"],
        "split_answer": a.split, "split_ok": r["split_ok"], "graphemes": r["graphemes"],
        "vowel_team": r["vowel_team"],
    }])
    return r


@app.post("/api/split/finish")
def split_finish():
    settings = load_settings()
    _clear_saved("split")
    return {"awards": _with_achievements(missions.complete_activity(store, settings, "split"), settings)}


# ---------------------------------------------------------------- sound match

@app.post("/api/match/session")
def match_session():
    cfg = load_settings()["match"]
    sess = match.new_session(store, cfg["rounds_per_session"], cfg["cards_per_round"])
    return match.public(sess, lambda f: f"/phonics-sounds/{f}")


class MatchAnswer(BaseModel):
    session: str
    round: int
    selected: list[str]


@app.post("/api/match/answer")
def match_answer(a: MatchAnswer):
    try:
        return match.check(store, a.session, a.round, a.selected)
    except ValueError as e:
        _bad(e)


@app.post("/api/match/finish")
def match_finish():
    settings = load_settings()
    _clear_saved("match")
    return {"awards": _with_achievements(missions.complete_activity(store, settings, "match"), settings)}


# ---------------------------------------------------------------- aquarium

@app.get("/api/aquarium")
def aquarium_view():
    return aquarium.view(store)


class Buy(BaseModel):
    item: str


@app.post("/api/aquarium/buy")
def aquarium_buy(b: Buy):
    try:
        aquarium.buy(store, b.item)
    except ValueError as e:
        _bad(e)
    return {**aquarium.view(store), "awards": achievements.check(store, load_settings())}


class Layout(BaseModel):
    positions: dict[str, dict]


@app.post("/api/aquarium/layout")
def aquarium_layout(l: Layout):
    if aquarium.save_layout(store, l.positions):
        _bump("rearrangements")
    return {"awards": achievements.check(store, load_settings())}


class Use(BaseModel):
    slot: str
    item: str | None = None


@app.post("/api/aquarium/use")
def aquarium_use(u: Use):
    if u.slot not in ("background", "sand"):
        raise HTTPException(400, "bad slot")
    try:
        aquarium.use_upgrade(store, u.item, u.slot)
    except ValueError as e:
        _bad(e)
    return aquarium.view(store)


class Archive(BaseModel):
    name: str | None = None


@app.post("/api/aquarium/archive")
def aquarium_archive(a: Archive):
    try:
        aquarium.archive(store, a.name)
    except ValueError as e:
        _bad(e)
    return {**aquarium.view(store), "awards": achievements.check(store, load_settings())}


@app.post("/api/fish-whisperer")
def fish_whisperer():
    _bump("fish_whisperer", 1)
    return {"awards": achievements.check(store, load_settings())}


# ---------------------------------------------------------------- grown-ups

@app.get("/api/progress")
def progress_report():
    meta = _meta()
    day = scheduler.current_day(meta, scheduler.today())
    progress = store.all_progress()
    reviews = store.reviews()
    words = store.all_words()
    rows = []
    for w in words.values():
        p = progress.get(w["id"])
        rows.append({
            "word": w["word"], "tags": w["tags"], "status": scheduler.status(p, day),
            "reps": p["reps"] if p else 0, "lapses": p["lapses"] if p else 0,
            "streak": p["streak"] if p else 0,
            "difficulty": round(p["card"]["difficulty"], 1) if p else None,
            "due_in": scheduler.due_day(p) - day if p and not p["retired"] else None,
            "last_review": p["last_review"] if p else None,
            "level": (w.get("rank") or {}).get("level"),
        })
    recent = [{**r, "word": words[r["id"]]["word"] if r["id"] in words else r["id"]} for r in reviews[-50:][::-1]]
    return {"words": rows, "recent": recent, "practice_day": meta["practice_day"],
            "last_practice_date": meta["last_practice_date"], **_levels_report(words, progress, day)}


def _levels_report(words: dict, progress: dict, day: int) -> dict:
    settings = load_settings()
    if settings["ranking"]["mode"] != "level":
        return {"ranking": None}
    info = scheduler.pace(words, progress, settings, day)
    levels = {}
    for wid, w in words.items():
        lv = (w.get("rank") or {}).get("level")
        if lv:
            row = levels.setdefault(lv, {"level": lv, "words": 0, "introduced": 0, "mastered": 0,
                                         "skipped": lv < settings["ranking"].get("start_level", 1)})
            row["words"] += 1
            row["introduced"] += wid in progress
            row["mastered"] += bool(progress.get(wid, {}).get("retired"))
    new = [wid for wid in words if wid not in progress]
    upcoming = scheduler.new_queue(new, words, progress, settings, day, info)[:20]
    return {"ranking": {"pace": info, "levels": [levels[k] for k in sorted(levels)],
                        "unranked": sum(1 for w in words.values() if "order" not in (w.get("rank") or {})),
                        "upcoming": [{"word": words[w]["word"], "level": (words[w].get("rank") or {}).get("level")}
                                     for w in upcoming]}}


@app.get("/api/backup")
def backup():
    """Everything in the database as one JSON file (the same format as data/db.json)."""
    import json
    name = f"spelling-backup-{scheduler.today().isoformat()}.json"
    return Response(json.dumps(store.dump(), ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@app.get("/api/economy")
def economy_report():
    view = aquarium.view(store)
    prices = {i["id"]: i["price"] for i in view["shop"]}
    owned = {i["id"] for i in view["shop"] if i["owned"]}
    earned = sorted(store.docs(achievements.EARNED).values(), key=lambda a: a["ts"], reverse=True)
    return {**economy.report(store, prices, owned), "achievements": earned,
            "missions": missions.completed(store)[-30:]}


app.mount("/media", StaticFiles(directory=store.media_dir), name="media")
# check_dir=False: the clips aren't in git, so a fresh checkout can still start (sound match just stays silent).
app.mount("/phonics-sounds", StaticFiles(directory=match.CLIPS_DIR, check_dir=False), name="phonics-sounds")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def revalidate_app_files(request, call_next):
    # Browsers otherwise keep using old copies of the JS/CSS modules after an update, and a mix of
    # old and new modules breaks the page. "no-cache" still uses the cached copy when it's unchanged.
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path in ("/", "/progress"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.middleware("http")
async def require_sign_in(request, call_next):
    path = request.url.path
    if not auth.enabled() or auth.is_open(path) or auth.valid_cookie(request.cookies.get(auth.COOKIE), load_settings()):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "Please sign in"}, status_code=401)
    if path in ("/", "/progress"):
        return RedirectResponse(f"/login?next={path}", status_code=303)
    return Response(status_code=401)


class Login(BaseModel):
    username: str
    password: str


@app.post("/api/login")
async def login(body: Login, request: Request):
    if not auth.check_password(load_settings(), body.username, body.password):
        await asyncio.sleep(1)   # slows down guessing
        raise HTTPException(401, "That name or password isn't right. Try again!")
    resp = JSONResponse({"ok": True})
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(auth.COOKIE, auth.make_cookie(body.username), max_age=auth.MAX_AGE,
                    httponly=True, samesite="lax", secure=https)
    return resp


@app.get("/login")
def login_page():
    return FileResponse(STATIC / "login.html")


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/progress")
def progress_page():
    return FileResponse(STATIC / "progress.html")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")
