"""Sound match: a phonics sound plays and she picks every word that contains it.

Sounds come from app/sounds.txt; the clips live in phonics_sounds/ (the media bucket on Cloud Run). Each word's letter-to-sound
alignment (app/phonics.py) is mapped onto those sounds per grapheme, so "dog" (o)
and "saw" (aw) get the clips the manifest assigns to each spelling even though the
dictionary uses the same vowel code for both.
"""
import csv
import os
import random
import uuid
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from .config import DATA_DIR, ROOT

SOUNDS_TXT = Path(__file__).with_name("sounds.txt")   # the list of sounds (in the repo)
LOCAL_CLIPS = ROOT / "phonics_sounds"                 # the clips on this Mac (not in git)


def _clips_dir() -> Path:
    """Where the sound clips live. On Cloud Run that's the media bucket, mounted at <data>/media; on this
    Mac it's phonics_sounds/ (the clips aren't in git). SPELLING_SOUND_CLIPS_DIR overrides both."""
    if env := os.environ.get("SPELLING_SOUND_CLIPS_DIR"):
        return Path(env)
    bucket = DATA_DIR / "media" / "phonics_sounds"
    return bucket if bucket.is_dir() else LOCAL_CLIPS


CLIPS_DIR = _clips_dir()
SESSIONS = "match_sessions"
RESULTS = "match_results"

VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
SINGLE = {
    "B": "b", "K": "k", "D": "d", "F": "f", "G": "g", "HH": "h", "JH": "j", "L": "l", "M": "m", "N": "n",
    "P": "p", "R": "r", "S": "s", "T": "t", "V": "v", "W": "w", "Y": "y", "Z": "z", "SH": "sh", "CH": "ch",
    "TH": "th", "DH": "th_voiced", "NG": "ng", "ZH": "zh", "AE": "a_short", "EH": "e_short", "IH": "i_short",
    "EY": "ai", "IY": "ee", "AY": "igh", "OW": "oa", "UW": "oo_long", "UH": "oo_short", "AW": "ow", "OY": "oy",
    "ER": "er",
}
MULTI = {("K", "S"): "ks", ("AA", "R"): "ar", ("AO", "R"): "or", ("IH", "R"): "ear", ("IY", "R"): "ear",
         ("EH", "R"): "air", ("EY", "R"): "air", ("UH", "R"): "ure"}
# Near-miss distractors: sounds easily confused with each other.
NEIGHBOURS = {
    "b": ["p"], "p": ["b"], "d": ["t"], "t": ["d"], "g": ["k"], "k": ["g"], "v": ["f"], "f": ["v", "th"],
    "z": ["s"], "s": ["z", "sh"], "th": ["th_voiced", "f"], "th_voiced": ["th", "d"], "j": ["ch"], "ch": ["j", "sh"],
    "sh": ["ch", "s"], "m": ["n"], "n": ["m", "ng"], "ng": ["n"], "l": ["r"], "r": ["w", "l"], "w": ["r"],
    "a_short": ["e_short", "u_short"], "e_short": ["i_short", "a_short"], "i_short": ["e_short", "ee"],
    "o_short": ["u_short", "aw"], "u_short": ["o_short", "a_short"], "ai": ["e_short", "ee"], "ee": ["i_short", "ai"],
    "igh": ["ai", "oy"], "oa": ["ow", "or"], "oo_long": ["oo_short"], "oo_short": ["oo_long", "u_short"],
    "ow": ["oa", "oy"], "oy": ["igh", "ow"], "er": ["ar", "or"], "ar": ["or", "er"], "or": ["ar", "aw"], "aw": ["or", "o_short"],
    "ear": ["air"], "air": ["ear"],
}


# Same spelling, two pronunciations: confusing when you can't hear which one is meant.
HETERONYMS = {"bow", "lead", "live", "read", "wind", "tear", "wound", "row", "sow", "bass", "does", "dove",
              "use", "used", "close", "wound", "minute", "object", "present", "record"}


def sound_of(grapheme: str, phones: tuple) -> str | None:
    """Which clip a grapheme's sound belongs to (None = no clip / too ambiguous)."""
    if len(phones) > 1:
        return MULTI.get(tuple(phones))
    p = phones[0]
    if p == "AO":
        return "o_short" if grapheme == "o" else "aw"     # saw, ball, taught: no r, so not the "or" clip
    if p == "AA":
        return "o_short" if grapheme == "o" else None
    if p == "AH":
        return "u_short" if grapheme in ("u", "o", "oo", "ou") else None
    return SINGLE.get(p)


@lru_cache(maxsize=1)
def manifest() -> dict[str, dict]:
    """sound id (file stem) -> {file, ipa, letters, examples}. Duplicate rows merge."""
    out = {}
    with open(SOUNDS_TXT, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            sid = row["file"].rsplit(".", 1)[0]
            s = out.setdefault(sid, {"id": sid, "file": row["file"], "ipa": row["sound"], "letters": [], "examples": []})
            s["letters"] += [x.strip() for x in row["letters"].split("/")]
            s["examples"] += [x.strip() for x in row["examples"].split(",")]
    return out


def word_sounds(w: dict) -> list[str | None] | None:
    ph = w.get("phonics") or {}
    if ph.get("status") != "ok":
        return None
    return [sound_of(g, tuple(p)) for g, p in zip(ph["graphemes"], ph["phonemes"])]


def pool(words: dict) -> list[dict]:
    """Words whose every sound maps to a clip."""
    out = []
    for w in words.values():
        if w["word"] in HETERONYMS:
            continue
        sounds = word_sounds(w)
        if sounds and all(sounds):
            out.append({"id": w["id"], "word": w["word"], "graphemes": w["phonics"]["graphemes"],
                        "phonemes": [tuple(p) for p in w["phonics"]["phonemes"]], "sounds": sounds})
    return out


def _phones_of(sound: str, words: list[dict]) -> set[str]:
    return {p for w in words for s, ph in zip(w["sounds"], w["phonemes"]) if s == sound for p in ph}


def _ambiguous(w: dict, target: str, target_phones: set[str]) -> bool:
    """True if a different sound in the word shares phonemes with the target, e.g. box for /k/
    (x = one sound /ks/) or saw for short o (same vowel code, different clip)."""
    tv = target_phones & VOWELS
    for s, ph in zip(w["sounds"], w["phonemes"]):
        if s == target:
            continue
        if tv and set(ph) & tv:
            return True
        if not tv and set(ph) & target_phones:
            return True
    return False


def playable(words: dict, min_pos: int = 3) -> dict[str, list[dict]]:
    """Sound id -> eligible words, for sounds with a clip and enough examples."""
    pl = pool(words)
    out = {}
    for sid in manifest():
        tp = _phones_of(sid, pl)
        if not tp:
            continue
        elig = [w for w in pl if not _ambiguous(w, sid, tp)]
        if sum(sid in w["sounds"] for w in elig) >= min_pos and sum(sid not in w["sounds"] for w in elig) >= 5:
            out[sid] = elig
    return out


def _spans(w: dict, target: str) -> list[list[int]]:
    spans, pos = [], 0
    for g, s in zip(w["graphemes"], w["sounds"]):
        if s == target:
            spans.append([pos, pos + len(g)])
        pos += len(g)
    return spans


def build_round(sound: str, elig: list[dict], cards: int, rng=random) -> dict:
    pos = [w for w in elig if sound in w["sounds"]]
    neg = [w for w in elig if sound not in w["sounds"]]
    # Positives: spread across different spellings of the sound.
    by_spelling = defaultdict(list)
    for w in pos:
        by_spelling[next(g for g, s in zip(w["graphemes"], w["sounds"]) if s == sound)].append(w)
    n_pos = min(len(pos), rng.choice([2, 3, 3, 4]))
    spellings = list(by_spelling)
    rng.shuffle(spellings)
    chosen = []
    while len(chosen) < n_pos:
        for g in spellings:
            options = [w for w in by_spelling[g] if w not in chosen]
            if options and len(chosen) < n_pos:
                chosen.append(rng.choice(options))
    # Lookalikes: same letters as a spelling of the target, but a different sound (snow vs cow).
    spell_set = set(by_spelling)
    lookalikes = [w for w in neg if any(g in spell_set for g in w["graphemes"])]
    rng.shuffle(lookalikes)
    picks_neg = lookalikes[:2]
    near = [w for w in neg if w not in picks_neg and any(s in NEIGHBOURS.get(sound, []) for s in w["sounds"])]
    rng.shuffle(near)
    picks_neg += near[:2]
    rest = [w for w in neg if w not in picks_neg]
    rng.shuffle(rest)
    picks_neg += rest[: cards - len(chosen) - len(picks_neg)]
    deck = chosen + picks_neg
    rng.shuffle(deck)
    m = manifest()[sound]
    shown = {w["word"] for w in deck}
    hint = next((e for e in m["examples"] if e not in shown), None)
    return {
        "sound": sound, "audio": m["file"], "hint": hint,
        "cards": [{"id": w["id"], "word": w["word"]} for w in deck],
        "positives": [w["id"] for w in chosen],
        "lookalikes": [w["id"] for w in picks_neg if w in lookalikes],
        "spans": {w["id"]: _spans(w, sound) for w in chosen},
    }


def new_session(store, rounds: int, cards: int, rng=random) -> dict:
    words = store.all_words()
    play = playable(words)
    results = store.records(RESULTS)
    tally = defaultdict(lambda: [0, 0])
    for r in results:
        tally[r["sound"]][0] += r["correct"]
        tally[r["sound"]][1] += 1

    def weight(sid):
        ok, n = tally[sid]
        return 2.0 if n == 0 else 1.0 + 3.0 * (1 - ok / n)

    sounds, options = [], list(play)
    for _ in range(min(rounds, len(options))):
        sid = rng.choices(options, weights=[weight(s) for s in options])[0]
        options.remove(sid)
        sounds.append(sid)
    sess = {"id": uuid.uuid4().hex[:10], "rounds": [build_round(s, play[s], cards, rng) for s in sounds]}
    store.put_docs(SESSIONS, [sess])
    return sess


def _intro_url(r: dict, audio_url) -> str | None:
    """"The sound is /s/, as in sun" for this round, if those clips have been built."""
    from .sound_intros import INTRO_DIR, path_for
    p = path_for(r["sound"], r["hint"])
    return audio_url(p.relative_to(INTRO_DIR.parent).as_posix()) if p else None


def public(sess: dict, audio_url) -> dict:
    """What the browser gets before answering (no answers)."""
    return {"session": sess["id"], "rounds": [
        {"sound": r["sound"], "audio_url": audio_url(r["audio"]), "hint": r["hint"], "cards": r["cards"],
         "intro_url": _intro_url(r, audio_url)}
        for r in sess["rounds"]]}


def check(store, session_id: str, index: int, selected: list[str]) -> dict:
    sess = store.get_doc(SESSIONS, session_id)
    if not sess or not 0 <= index < len(sess["rounds"]):
        raise ValueError("unknown round")
    r = sess["rounds"][index]
    pos, sel = set(r["positives"]), set(selected)
    verdicts = {}
    for c in r["cards"]:
        i = c["id"]
        verdicts[i] = ("hit" if i in sel else "missed") if i in pos else ("wrong" if i in sel else "ok")
    correct = sel == pos
    store.append(RESULTS, [{
        "session": session_id, "round": index, "sound": r["sound"], "positives": r["positives"],
        "selected": sorted(sel), "correct": correct, "cards": [c["id"] for c in r["cards"]],
        "card_ok": [verdicts[c["id"]] in ("hit", "ok") for c in r["cards"]],
        "lookalikes": r["lookalikes"],
        "lookalikes_rejected": sum(1 for i in r["lookalikes"] if i not in sel),
    }])
    words = {c["id"]: c["word"] for c in r["cards"]}
    seen = [words[i][a:b] for i, spans in r["spans"].items() for a, b in spans]
    letters = list(dict.fromkeys(manifest()[r["sound"]]["letters"] + seen))
    return {"correct": correct, "verdicts": verdicts, "spans": r["spans"], "lookalikes": r["lookalikes"],
            "letters": letters}


def stats(store) -> dict:
    results = store.records(RESULTS)
    covered = {r["sound"] for r in results if r["correct"]}
    # A round only counts as a real try if at least one right word was tapped; otherwise
    # checking an empty round would "reject" every lookalike for free.
    tried = [bool(set(r["selected"]) & set(r["positives"])) for r in results]
    run = best = 0
    for r, t in zip(results, tried):
        for ok in (r["card_ok"] if t else [False]):
            run = run + 1 if ok else 0
            best = max(best, run)
    return {
        "match_streak": best,
        "lookalikes_rejected": sum(r["lookalikes_rejected"] for r, t in zip(results, tried) if t),
        "sounds_covered": len(covered),
        "all_sounds_covered": int(bool(covered) and set(playable(store.all_words())) <= covered),
    }
