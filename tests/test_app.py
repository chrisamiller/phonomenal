import importlib
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from app.config import load_settings
from app.grading import grade
from app.scheduler import advance_day, build_session, due_day, new_meta, record, status

NOW = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)
DAY = 10


@pytest.fixture
def settings():
    return load_settings()


def words(n, tag="t"):
    return {f"w{i}": {"id": f"w{i}", "word": f"word{i}", "tags": [tag], "added": f"{i:04d}"} for i in range(n)}


def test_grade_correct_and_highlights():
    assert grade(" because ", "because")["correct"]
    r = grade("becuse", "because")
    assert not r["correct"]
    assert [l["ch"] for l in r["letters"] if not l["ok"]] == ["a"]


def test_grade_case_is_lenient_with_note():
    r = grade("january", "January")
    assert r["correct"] and "capital" in r["case_note"]
    assert not grade("january", "January", strict_case=True)["correct"]


def test_first_session_limits_new_words(settings):
    no_top_up = {**settings, "session": {**settings["session"], "top_up_with_new": False}}
    picks = build_session(words(50), {}, no_top_up, DAY)
    assert len(picks) == settings["session"]["max_new_per_session"]
    assert all(p["kind"] == "new" for p in picks)


def test_top_up_fills_session_with_new_words(settings):
    # Nothing due and today's new-word allowance used up: still a full session.
    progress = {}
    for i in range(settings["session"]["max_new_per_day"]):
        progress[f"w{i}"], _ = record(None, f"w{i}", True, "easy", settings, DAY, NOW)
    picks = build_session(words(40), progress, settings, DAY)
    assert len(picks) == settings["session"]["size"]
    assert all(p["kind"] == "new" for p in picks)


def test_new_word_tag_order(settings):
    ws = words(5, "advanced-spelling-words")
    ws["custom"] = {"id": "custom", "word": "fuzzy", "tags": ["custom-words"], "added": "9999"}
    assert "custom" in {p["id"] for p in build_session(ws, {}, settings, DAY)}


def test_daily_new_limit(settings):
    progress = {}
    for i in range(settings["session"]["max_new_per_day"]):
        progress[f"w{i}"], _ = record(None, f"w{i}", True, "easy", settings, DAY, NOW)
    no_top_up = {**settings, "session": {**settings["session"], "top_up_with_new": False}}
    picks = build_session(words(40), progress, no_top_up, DAY)
    assert not [p for p in picks if p["kind"] == "new"]


def test_session_mixes_difficulty(settings):
    progress = {}
    for i in range(60):
        choice = ["easy", "little_hard", "guessed"][i % 3]
        progress[f"w{i}"], _ = record(None, f"w{i}", i % 4 != 0, choice, settings, DAY - 30, NOW)
    picks = build_session(words(60), progress, settings, DAY, rng=random.Random(0))
    assert len(picks) == settings["session"]["size"]
    diffs = [progress[p["id"]]["card"]["difficulty"] for p in picks]
    assert min(diffs) < settings["difficulty"]["easy_below"]
    assert any(progress[p["id"]]["streak"] == 0 for p in picks)
    assert diffs[0] < settings["difficulty"]["easy_below"]  # starts on an easy word


def test_mastery_and_unretire(settings):
    p, day = None, DAY
    for _ in range(4):
        p, _ = record(p, "w", True, "easy", settings, day, NOW)
        day = due_day(p)
    assert p["retired"]
    p, rating = record(p, "w", False, None, settings, day, NOW)
    assert rating == "Again" and not p["retired"] and p["streak"] == 0


def test_intervals_are_in_practice_days(settings):
    p, _ = record(None, "w", False, None, settings, DAY, NOW)
    assert due_day(p) == DAY + 1  # a miss comes back the next practice day
    assert status(p, DAY) == "learning" and status(p, DAY + 1) == "due"


def test_practice_clock_ignores_days_off(settings):
    m = advance_day(new_meta(), date(2026, 11, 2), settings)
    m = advance_day(m, date(2026, 11, 2), settings)  # second session same day
    assert m["practice_day"] == 1
    m = advance_day(m, date(2026, 11, 5), settings)  # skipped two days
    assert m["practice_day"] == 2 and m["return_day"] is None
    m = advance_day(m, date(2026, 11, 20), settings)  # vacation
    assert m["practice_day"] == 3 and m["return_day"] == 3


def test_returning_day_is_review_first(settings):
    n = settings["session"]["size"] + 5
    progress = {f"w{i}": record(None, f"w{i}", True, "little_hard", settings, DAY - 5, NOW)[0] for i in range(n)}
    picks = build_session(words(2 * n), progress, settings, DAY, returning=True)
    assert len(picks) == settings["session"]["size"]
    assert not [p for p in picks if p["kind"] == "new"]
    # With few reviews due, new words still fill the gap.
    picks = build_session(words(2 * n), {"w0": progress["w0"]}, settings, DAY, returning=True)
    assert [p for p in picks if p["kind"] == "new"]


def test_api_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("SPELLING_DATA_DIR", str(tmp_path))
    import app.config, app.main
    importlib.reload(app.config)
    main = importlib.reload(app.main)
    from fastapi.testclient import TestClient

    main.store.put_words([
        {"id": "because", "word": "because", "sentence": "I smiled because it was sunny.", "audio": None,
         "sentence_audio": None, "tags": ["t"], "added": "1"},
        {"id": "friend", "word": "friend", "sentence": "", "audio": "friend.mp3",
         "sentence_audio": None, "tags": ["t"], "added": "2"},
    ])
    c = TestClient(main.app)
    cards = {x["id"]: x for x in c.post("/api/session").json()["cards"]}
    assert main.store.get_meta()["practice_day"] == 1
    assert cards["because"]["sentence_blank"] == "I smiled _____ it was sunny."
    assert cards["because"]["speak_word"] == "because"
    assert cards["friend"]["audio_url"] == "/media/friend.mp3" and cards["friend"]["speak_word"] is None

    r = c.post("/api/answer", json={"id": "because", "typed": "becuz"}).json()
    assert not r["correct"] and r["recorded"]
    assert not c.post("/api/answer", json={"id": "because", "typed": "becuz", "practice": True}).json()["recorded"]

    assert c.post("/api/answer", json={"id": "friend", "typed": "friend"}).json()["correct"]
    assert c.post("/api/rate", json={"id": "friend", "typed": "frend", "choice": "easy"}).status_code == 400
    r = c.post("/api/rate", json={"id": "friend", "typed": "friend", "choice": "easy"})
    assert r.status_code == 200 and r.json()["mastered"]
    assert [a["amount"] for a in r.json()["awards"] if a.get("source") == "correct_word"] == [2]   # right first try

    c.post("/api/session")  # same day: clock doesn't move
    assert main.store.get_meta()["practice_day"] == 1
    status = c.get("/api/status").json()
    assert status["learning"] == 1 and status["mastered"] == 1   # friend: right first time, rated easy
    prog = c.get("/api/progress").json()
    assert [r["word"] for r in prog["recent"]] == ["friend", "because"]
    assert {w["word"]: w["due_in"] for w in prog["words"]}["because"] == 1


def test_audio_queue(settings):
    from app.cli import audio_queue
    ws = {
        "a": {"id": "a", "word": "cat", "sentence": "The cat sat.", "audio": "a.mp3", "audio_source": "anki",
              "sentence_audio": None, "sentence_audio_source": None, "added": "1"},
        "b": {"id": "b", "word": "dog", "sentence": "", "audio": "b.m4a", "audio_source": "macos-say",
              "sentence_audio": None, "sentence_audio_source": None, "added": "2"},
        "c": {"id": "c", "word": "pig", "sentence": "", "audio": None, "audio_source": None,
              "sentence_audio": None, "sentence_audio_source": None, "added": "3"},
    }
    q = [(i["id"], i["kind"], i["reason"]) for i in audio_queue(ws, settings)]
    assert q == [("a", "sentence", "missing"), ("b", "word", "replace macos-say"), ("c", "word", "missing")]
