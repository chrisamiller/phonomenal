import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import phonics

REAL_CMUDICT = Path(__file__).resolve().parent.parent / "data" / "phonics" / "cmudict.dict"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPELLING_DATA_DIR", str(tmp_path))
    import app.config
    importlib.reload(app.config)
    main = importlib.reload(importlib.import_module("app.main"))
    main.store.put_words([
        {"id": w, "word": w, "sentence": f"I see a {w}.", "audio": None, "sentence_audio": None,
         "tags": ["t"], "added": str(i), "phonics": phonics.analyse(w)}
        for i, w in enumerate(["cat", "ship", "rain", "box", "night", "stop"])
    ])
    prompts = tmp_path / "prompts.txt"
    prompts.write_text("# Opinions\nWhat is the best season?\n# Quick questions\nWhat makes you laugh?\n")
    main.writing.import_prompts(main.store, prompts)
    return TestClient(main.app), main


def credits(main):
    return main.economy.balance(main.store)


@pytest.mark.skipif(not REAL_CMUDICT.exists(), reason="CMU dictionary not downloaded")
def test_alignment_conventions():
    def split(w):
        return "|".join(phonics.analyse(w).get("graphemes", [])) or phonics.analyse(w)["reason"]
    assert split("prowl") == "p|r|ow|l"
    assert split("box") == "b|o|x"          # x is one sound
    assert split("quit") == "qu|i|t"        # qu is one sound
    assert split("ball") == "b|a|ll"        # double letters are one sound
    assert split("stop") == "s|t|o|p"       # blends stay separate
    assert split("knee") == "kn|ee"
    assert split("warm") == "w|ar|m"
    assert split("cake") == "silent e"      # silent-e words are left out
    assert split("smiled") == "silent e"
    assert split("rolled") == "r|o|ll|ed"
    assert split("think") == "th|i|nk"     # nk is one unit (UFLI)
    assert split("bank") == "b|a|nk"


def test_mission_flow_and_credits(client):
    c, main = client
    home = c.get("/api/home").json()
    assert home["mission"]["chosen"] is None and home["balance"] == 0 and home["has_prompts"]
    assert c.post("/api/mission/choose", json={"extras": []}).status_code == 400
    assert c.post("/api/mission/choose", json={"extras": ["writing"]}).json()["chosen"] == ["spelling", "writing"]

    awards = c.post("/api/activity/done", json={"activity": "spelling"}).json()["awards"]
    assert [a["source"] for a in awards if a["kind"] == "credits"] == ["activity"]
    # Doing it again the same day earns the smaller bonus-practice amount.
    again = c.post("/api/activity/done", json={"activity": "spelling"}).json()["awards"]
    assert [a["source"] for a in again] == ["activity_repeat"]

    today = c.get("/api/writing/today").json()
    assert today["prompt"]["text"] in ("What is the best season?", "What makes you laugh?")
    assert c.post("/api/writing/submit", json={"text": "Too short."}).status_code == 400
    text = "I like summer. It is warm and sunny. We swim every day."
    r = c.post("/api/writing/submit", json={"text": text}).json()
    assert r["sentences"] == 3
    kinds = {(a["kind"], a.get("source") or a.get("id")) for a in r["awards"]}
    assert ("credits", "mission") in kinds
    assert ("achievement", "first-splash") in kinds and ("achievement", "first-draft") in kinds
    # activity 20 + repeat 10 + activity 20 + mission 40 + first-splash 10 + first-draft 10,
    # plus Early Bird / Night Owl / Weekend Warrior, depending on when the test runs
    clock = sum(a["credits"] for a in r["awards"] if a.get("achievement") in ("early-bird", "night-owl", "weekend-warrior"))
    assert credits(main) == 110 + clock
    assert c.get("/api/writing/today").json()["done"]
    csv = c.get("/api/export/writing").text
    assert "We swim every day." in csv

    week = c.get("/api/home").json()["week"]
    assert week["count"] == 1 and week["goal"] == 5


def test_split_game(client):
    c, main = client
    s = c.post("/api/split/session").json()
    ids = {w["id"] for w in s["words"]}
    assert ids <= {"cat", "ship", "rain", "box", "night", "stop"}
    r = c.post("/api/split/answer", json={"session": s["session"], "id": "ship", "count": 3, "split": [2, 3]}).json()
    assert r["count_ok"] and r["split_ok"] and r["graphemes"] == ["sh", "i", "p"]
    r = c.post("/api/split/answer", json={"session": s["session"], "id": "rain", "count": 4, "split": [1, 2, 3]}).json()
    assert not r["count_ok"] and not r["split_ok"] and r["boundaries"] == [1, 3] and r["vowel_team"]
    awards = c.post("/api/split/finish").json()["awards"]
    assert any(a.get("detail") == "split" for a in awards)


def test_aquarium_and_economy(client):
    c, main = client
    assert c.post("/api/aquarium/buy", json={"item": "guppy"}).status_code == 400  # no credits yet
    main.economy.award(main.store, "test", 100)
    view = c.post("/api/aquarium/buy", json={"item": "guppy"}).json()
    assert credits(main) == 60 + 6  # 100 - 40, plus First Fish achievement
    assert any(a.get("id") == "first-fish" for a in view["awards"])
    uid = view["project"]["items"][0]["uid"]
    c.post("/api/aquarium/layout", json={"positions": {uid: {"x": 50, "y": 30}}})
    assert main.store.get_meta()["counters"]["rearrangements"] == 1

    main.economy.award(main.store, "test", 100)
    c.post("/api/aquarium/buy", json={"item": "bg-reef"})
    assert c.get("/api/aquarium").json()["project"]["tank"]["background"] == "bg-reef"
    assert c.post("/api/aquarium/use", json={"slot": "background", "item": "bg-deep"}).status_code == 400

    view = c.post("/api/aquarium/archive", json={"name": "My first tank"}).json()
    assert view["project"]["items"] == [] and view["gallery"][0]["name"] == "My first tank"
    assert any(a.get("id") == "fresh-start" for a in view["awards"])

    eco = c.get("/api/economy").json()
    assert eco["spent_total"] == 140 and eco["purchases"][0]["item"] == "guppy"
    assert eco["most_expensive_unowned"]["item"] == "whale-shark"


def test_rematch_awards_credits(client):
    c, main = client
    c.post("/api/session")
    c.post("/api/answer", json={"id": "cat", "typed": "kat"})       # a miss
    r = c.post("/api/rate", json={"id": "cat", "typed": "cat", "choice": "easy"}).json()
    assert any(a.get("source") == "rematch" for a in r["awards"])


def test_trophy_shelf_hides_hidden(client):
    c, _ = client
    shelf = c.get("/api/trophies").json()
    assert shelf["items"] == [] and shelf["unearned"] == len(main_achievements())
    c.post("/api/mission/choose", json={"extras": ["split"]})
    c.post("/api/activity/done", json={"activity": "spelling"})
    c.post("/api/split/finish")
    shelf = c.get("/api/trophies").json()
    assert [i["id"] for i in shelf["items"] if i["today"]] == ["first-splash"] or "first-splash" in {i["id"] for i in shelf["items"]}
    assert all(i["today"] for i in shelf["items"])


def main_achievements():
    from app import achievements
    return achievements.load()


@pytest.mark.skipif(not REAL_CMUDICT.exists(), reason="CMU dictionary not downloaded")
def test_sound_match(client):
    c, main = client
    extra = ["cow", "out", "now", "town", "snow", "boat", "cat", "pig", "sun", "bed", "hot", "dog",
             "shout", "loud", "grow", "fish", "book", "moon", "red", "map"]
    main.store.put_words([{"id": w, "word": w, "sentence": "", "audio": None, "sentence_audio": None,
                           "tags": ["t"], "added": "9", "phonics": phonics.analyse(w)} for w in extra])
    sess = main.match.new_session(main.store, 1, 8)
    rnd = sess["rounds"][0]
    pub = c.post("/api/match/session").json()
    assert "positives" not in pub["rounds"][0] and pub["rounds"][0]["audio_url"].startswith("/phonics-sounds/")
    # Answer the stored round perfectly, then badly.
    r = c.post("/api/match/answer", json={"session": sess["id"], "round": 0, "selected": rnd["positives"]}).json()
    assert r["correct"] and all(v in ("hit", "ok") for v in r["verdicts"].values())
    r = c.post("/api/match/answer", json={"session": sess["id"], "round": 0, "selected": []}).json()
    assert not r["correct"] and "missed" in r["verdicts"].values()
    # Checking an empty round doesn't count toward the lookalike achievement.
    before = main.match.stats(main.store)["lookalikes_rejected"]
    for _ in range(3):
        c.post("/api/match/answer", json={"session": sess["id"], "round": 0, "selected": []})
    assert main.match.stats(main.store)["lookalikes_rejected"] == before
    assert any(a.get("detail") == "match" for a in c.post("/api/match/finish").json()["awards"])


@pytest.mark.skipif(not REAL_CMUDICT.exists(), reason="CMU dictionary not downloaded")
def test_sound_mapping_follows_spelling():
    from app import match
    def sounds(w):
        a = phonics.analyse(w)
        return [match.sound_of(g, tuple(p)) for g, p in zip(a["graphemes"], a["phonemes"])]
    assert sounds("dog") == ["d", "o_short", "g"]
    assert sounds("saw") == ["s", "aw"]          # aw has its own clip; "or" has an r
    assert sounds("box") == ["b", "o_short", "ks"]
    assert sounds("snow")[-1] == "oa" and sounds("cow")[-1] == "ow"


def test_streak_achievements_repeat(client):
    c, main = client
    def mission(day):
        main.store.put_docs("missions", [{"id": day, "iso_week": main.economy.iso_week(__import__("datetime").date.fromisoformat(day)),
                                          "chosen": ["spelling"], "done": {}, "completed_at": f"{day}T17:00:00+00:00"}])
    for d in ["2026-10-01", "2026-10-02", "2026-10-03"]:
        mission(d)
    awards = main.achievements.check(main.store, main.load_settings())
    assert [a["id"] for a in awards if a.get("achievement") == "on-a-roll"] == ["on-a-roll#1"]
    for d in ["2026-10-10", "2026-10-11", "2026-10-12", "2026-10-13", "2026-10-14"]:
        mission(d)
    ids = {a["id"] for a in main.achievements.check(main.store, main.load_settings())}
    assert {"on-a-roll#2", "high-five#1"} <= ids
    shelf = {i["id"]: i for i in c.get("/api/trophies").json()["items"]}
    assert shelf["on-a-roll"]["times"] == 2


def test_bonus_replays_earn_capped_credits(client):
    c, main = client
    c.post("/api/mission/choose", json={"extras": ["split"]})
    first = c.post("/api/split/finish").json()["awards"]
    assert any(a.get("source") == "activity" for a in first)
    settings = main.load_settings()
    repeat, cap = settings["credits"]["activity_repeat"], settings["credits"]["repeat_daily_cap"]
    earned = 0
    for _ in range(cap // repeat + 3):
        aw = c.post("/api/split/finish").json()["awards"]
        earned += sum(a["amount"] for a in aw if a.get("source") == "activity_repeat")
    assert earned == cap
    assert c.get("/api/home").json()["repeat_credits"] == 0


def test_retuned_thresholds_hide_stale_awards(client):
    c, main = client
    main.store.put_docs("achievements", [{"id": "same-letters-different-sound", "achievement": "same-letters-different-sound",
                                          "tier": None, "name": "x", "description": "x", "credits": 15,
                                          "ts": "2026-10-30T12:00:00-05:00"}])
    shelf = c.get("/api/trophies").json()
    assert shelf["items"] == [] and shelf["unearned"] == len(main_achievements())


def test_google_audio_batches_keep_word_and_sentence(client, monkeypatch):
    _, main = client
    from app import cli, tts_google
    monkeypatch.setattr(tts_google, "synthesize", lambda text, voice, rate: b"ID3" + bytes(1000))
    cli.generate_audio(main.store, "google", None, None, 0.9, 3)
    assert not cli.audio_queue(main.store.all_words(), main.load_settings(), media_dir=main.store.media_dir)
    (main.store.media_dir / "cat.chirp.mp3").write_bytes(b"ID3")        # a broken clip is queued again
    assert [(i["id"], i["reason"]) for i in cli.audio_queue(main.store.all_words(), main.load_settings(),
                                                           media_dir=main.store.media_dir)] == [("cat", "broken file")]
    for w in main.store.all_words().values():
        assert w["audio_source"] == w["sentence_audio_source"] == "google-chirp3"
        assert main.store.has_media(w["audio"]) and w["sentence_audio"].endswith(".sentence.chirp.mp3")


def test_tank_upgrades_carry_over_and_stock_look_returns(client):
    c, main = client
    main.economy.award(main.store, "test", 500)
    c.post("/api/aquarium/buy", json={"item": "bg-reef"})
    c.post("/api/aquarium/buy", json={"item": "guppy"})
    assert c.post("/api/aquarium/use", json={"slot": "background", "item": None}).json()["project"]["tank"]["background"] is None
    c.post("/api/aquarium/archive", json={"name": "First"})
    view = c.get("/api/aquarium").json()
    assert next(i for i in view["shop"] if i["id"] == "bg-reef")["owned"]          # still hers in the new tank
    assert c.post("/api/aquarium/buy", json={"item": "bg-reef"}).status_code == 400  # no paying twice
    view = c.post("/api/aquarium/use", json={"slot": "background", "item": "bg-reef"}).json()
    assert view["project"]["tank"]["background"] == "bg-reef"


def test_saved_progress_lasts_until_midnight(client, monkeypatch):
    from datetime import date
    c, main = client
    monkeypatch.setattr(main.scheduler, "today", lambda: date(2026, 11, 9))
    assert c.get("/api/saved/spelling").json()["state"] is None
    assert c.post("/api/saved/nope", json={"state": {}}).status_code == 404
    c.post("/api/saved/spelling", json={"state": {"idx": 7, "label": "7 of 25 words"}})
    c.post("/api/saved/split", json={"state": {"idx": 2}})
    assert c.get("/api/saved/spelling").json()["state"]["idx"] == 7
    assert c.get("/api/home").json()["saved"] == {"spelling": "7 of 25 words", "split": "in progress"}
    c.post("/api/split/finish", json={})                               # finishing clears it
    assert c.get("/api/saved/split").json()["state"] is None
    monkeypatch.setattr(main.scheduler, "today", lambda: date(2026, 11, 10))   # past midnight: start over
    assert c.get("/api/saved/spelling").json()["state"] is None
    assert c.get("/api/home").json()["saved"] == {}
    assert c.get("/api/balance").json() == {"balance": credits(main)}
