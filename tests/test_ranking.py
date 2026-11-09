from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import ranking
from app.config import load_settings
from app.scheduler import build_session, pace, record

REAL_CMUDICT = Path(__file__).resolve().parent.parent / "data" / "phonics" / "cmudict.dict"
NOW = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)
DAY = 20
needs_cmu = pytest.mark.skipif(not REAL_CMUDICT.exists(), reason="CMU dictionary not downloaded")


@pytest.fixture
def settings():
    s = load_settings()
    s["session"]["top_up_with_new"] = False
    s["ranking"]["start_level"] = 1
    return s


def ranked(levels: list[int], **extra) -> dict:
    """Words already ranked: w0 is easiest. `extra` maps word id -> rank fields to override."""
    out = {}
    for i, lv in enumerate(levels):
        wid = f"w{i}"
        out[wid] = {"id": wid, "word": wid, "tags": ["t"], "added": f"{i:04d}",
                    "rank": {"level": lv, "order": i, "pattern": "a", "heart": False, "homophones": [], **extra.get(wid, {})}}
    return out


def answered(wids, correct: bool, settings, day=DAY - 1):
    progress = {}
    for w in wids:
        progress[w], _ = record(None, w, correct, "easy" if correct else None, settings, day, NOW)
    return progress


def new_ids(picks):
    return [p["id"] for p in picks if p["kind"] == "new"]


@needs_cmu
def test_spelling_features():
    from app import phonics
    cmu = phonics.cmudict()
    assert ranking.spell_pairs("cake", cmu) == [("c", "K"), ("a_e", "EY"), ("k", "K")]
    assert ranking.spell_pairs("don't", cmu)[-1] == ("t", "T")
    assert ranking.spell_pairs("nation", cmu)[-1] == ("tion", "SH AH N")
    assert [ranking.suffix_rules(w, cmu) for w in ("running", "making", "cried", "singing", "jumping")] == [1, 1, 1, 0, 0]
    stats = ranking.spelling_stats(["cat", "hat", "bat", "cake", "rain", "laugh"], cmu)
    easy = ranking.features("cat", cmu, stats, 1, 5.0)
    hard = ranking.features("laugh", cmu, stats, 1, 5.0)
    assert hard["surprise"] > easy["surprise"]


@needs_cmu
def test_rank_all_orders_easy_words_first(tmp_path):
    from app.store import LocalStore
    store = LocalStore(tmp_path)
    vocab = ["cat", "dog", "sun", "rain", "night", "their", "there", "necessary", "February", "beautiful", "running"]
    store.put_words([{"id": w, "word": w, "tags": ["spellquiz-grade-1"], "added": "0", "sentence": ""} for w in vocab])
    settings = load_settings()
    settings["ranking"]["levels"] = 3
    ranking.rank_all(store, settings)
    words = store.all_words()
    order = sorted(words, key=lambda w: words[w]["rank"]["order"])
    assert set(order[:3]) <= {"cat", "dog", "sun", "rain", "night"}
    assert set(order[-3:]) == {"necessary", "February", "beautiful"}
    assert words["necessary"]["rank"]["level"] == 3 and words["cat"]["rank"]["level"] == 1
    assert words["their"]["rank"]["homophones"] == ["there"] and words["their"]["rank"]["heart"]
    # Newly added words get ranked with the saved statistics.
    store.put_words([{"id": "hat", "word": "hat", "tags": ["spellquiz-grade-1"], "added": "1", "sentence": ""}])
    assert ranking.rank_missing(store, settings) == 1
    assert store.get_word("hat")["rank"]["level"] == 1


def test_new_words_come_easiest_first(settings):
    words = ranked([3, 1, 2, 1, 1, 2, 3, 1, 1, 1])
    assert new_ids(build_session(words, {}, settings, DAY))[:3] == ["w1", "w3", "w4"]


def test_priority_heart_and_homophone_rules(settings):
    words = ranked([1] * 12, w0={"heart": True}, w1={"heart": True}, w2={"homophones": ["w11"]})
    words["w9"]["tags"] = ["custom-words"]
    words["w9"]["rank"]["level"] = 5
    progress = answered(["w11"], True, settings, day=DAY - 2)     # w2's homophone was just introduced
    picks = new_ids(build_session(words, progress, settings, DAY))
    assert picks[0] == "w9"                                        # her own word, despite its level
    assert "w0" in picks and "w1" not in picks                     # one heart word per session
    assert "w2" not in picks


def test_struggling_pauses_new_words(settings):
    words = ranked([1] * 30)
    progress = answered([f"w{i}" for i in range(12)], False, settings)
    info = pace(words, progress, settings, DAY)
    assert info["factor"] == 0 and "No new words" in info["reason"]
    assert new_ids(build_session(words, progress, settings, DAY)) == []


def test_next_level_opens_when_previous_is_solid(settings):
    words = ranked([1] * 10 + [2] * 10 + [3] * 10)
    # Level 1 all introduced, mostly missed (but too few recent reviews to trigger the accuracy check).
    settings["ranking"]["pace_min_reviews"] = 100
    shaky = {**answered([f"w{i}" for i in range(7)], False, settings), **answered(["w7", "w8", "w9"], True, settings)}
    info = pace(words, shaky, settings, DAY)
    assert info["level"] == 2 and info["factor"] == 0.5 and not info["level_open"]
    picks = new_ids(build_session(words, shaky, settings, DAY))
    assert all(words[w]["rank"]["level"] == 2 for w in picks)      # no preview while level 1 is shaky

    solid = answered([f"w{i}" for i in range(10)], True, settings)
    info = pace(words, solid, settings, DAY)
    assert info["factor"] == 1 and info["level_open"]
    picks = new_ids(build_session(words, solid, settings, DAY))
    assert len(picks) == settings["session"]["max_new_per_session"]
    assert any(words[w]["rank"]["level"] == 3 for w in picks)       # a preview word from the next level


def test_start_level_skips_easier_words(settings):
    settings["ranking"]["start_level"] = 2
    words = ranked([1] * 10 + [2] * 10 + [3] * 10)
    words["w0"]["tags"] = ["custom-words"]                  # her own words still come, whatever the level
    progress = answered([f"w{i}" for i in range(1, 8)], False, settings, day=DAY - 3)   # shaky level-1 words
    settings["ranking"]["pace_min_reviews"] = 100
    info = pace(words, progress, settings, DAY)
    assert info["level"] == 2 and info["factor"] == 1               # level 2 isn't held back by level 1
    picks = new_ids(build_session(words, progress, settings, DAY))
    assert picks[0] == "w0" and all(words[w]["rank"]["level"] >= 2 for w in picks[1:])


def test_previews_rotate_up_to_max_level(settings):
    settings["ranking"]["preview_max_level"] = 4
    settings["session"]["max_new_per_session"] = 20
    settings["session"]["max_new_per_day"] = 20
    words = ranked([1] * 10 + [2] * 20 + [3] * 10 + [4] * 10 + [5] * 10)
    solid = answered([f"w{i}" for i in range(10)], True, settings)
    info = pace(words, solid, settings, DAY)
    from app.scheduler import new_queue
    queue = new_queue([w for w in words if w not in solid], words, solid, settings, DAY, info)
    first = [words[w]["rank"]["level"] for w in queue[:10]]
    assert first.count(2) == 8 and 3 in first and 4 in first     # stretch words from levels 3 and 4
    assert 5 not in [words[w]["rank"]["level"] for w in queue[:20]]  # nothing above the max while level 2 lasts


def test_easy_on_first_sight_is_mastered_for_good(settings):
    p, _ = record(None, "w0", True, "easy", settings, DAY, NOW)
    assert p["retired"] and p["known_on_sight"]
    later = build_session(ranked([1, 1]), {"w0": p}, settings, DAY + 365)
    assert "w0" not in [x["id"] for x in later]                    # not even as a spot check
    # Only the very first answer counts, and only when rated easy.
    assert not record(None, "w1", True, "little_hard", settings, DAY, NOW)[0]["retired"]
    missed, _ = record(None, "w1", False, None, settings, DAY, NOW)
    assert not record(missed, "w1", True, "easy", settings, DAY + 1, NOW)[0]["retired"]
    settings["mastery"]["easy_on_first_sight"] = False
    assert not record(None, "w1", True, "easy", settings, DAY, NOW)[0]["retired"]


def test_master_known_is_quiet(tmp_path, settings, capsys):
    from app import achievements, cli
    from app.store import LocalStore
    store = LocalStore(tmp_path)
    store.put_words(list(ranked([1, 1, 1]).values()))
    settings["mastery"]["easy_on_first_sight"] = False       # as before this feature existed
    for wid, ok, choice in [("w0", True, "easy"), ("w1", True, "little_hard"), ("w2", True, "easy"), ("w2", False, None)]:
        p, rating = record(store.get_progress(wid), wid, ok, choice, settings, DAY, NOW)
        store.save_review(p, {"id": wid, "ts": NOW.isoformat(), "day": DAY, "correct": ok, "rating": rating})
    cli.master_known(store, apply=True)
    prog = store.all_progress()
    assert prog["w0"]["retired"] and prog["w0"]["quiet"]
    assert not prog["w1"]["retired"] and not prog["w2"]["retired"]  # not easy / missed since
    assert achievements.compute_stats(store, load_settings())["words_mastered"] == 0
