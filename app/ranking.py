"""Difficulty ranking for introducing new words, easiest first.

Each word gets a *spelling* difficulty score (not a reading score) from:
  - surprise: how unexpected each sound's spelling is, in bits, using letter-sound statistics
    gathered from the whole word list (so silent letters, rare spellings like "ough", the
    unstressed "uh" sound in long words and magic-e all count)
  - syllables, suffix rules (doubling, dropping e, y to i), length in letters
  - how common the word is (wordfreq zipf score, saved on the word; needs requirements-tools.txt)
  - the lowest grade of any word list it appears in
Scores are split into levels; inside a level, words that share their trickiest spelling
pattern sit together so a session's new words practise one pattern.

`rank-words` (app/cli.py) ranks everything; `add` ranks just the new words.
"""
import bisect
import math
import re
from collections import Counter, defaultdict

from . import phonics

RANKING = "ranking"   # docs collection: spelling statistics and level thresholds

# Extra spellings for multi-syllable words. The games use phonics.G alone.
EXTRA_G = {
    "ti": ["SH"], "ci": ["SH"], "si": ["ZH", "SH"], "ture": ["CH ER"], "sure": ["ZH ER", "SH ER"],
    "le": ["AH L"], "el": ["AH L"], "al": ["AH L"], "il": ["AH L"], "ous": ["AH S"], "tion": ["SH AH N"],
    "sion": ["ZH AH N", "SH AH N"], "cian": ["SH AH N"], "ge": ["JH"], "ce": ["S"], "mn": ["M"], "bt": ["T"],
    "st": ["S"], "lk": ["K"], "lf": ["F"], "lm": ["M"], "io": ["IY AH", "AH"], "ia": ["IY AH"],
    "eo": ["IY AH"], "ier": ["IY ER"], "re": ["ER"], "our": ["ER"], "ar": ["ER"], "or": ["ER"],
    "e": ["IY", "EH", "AH", "IH"], "a": ["AH", "EY", "AE", "AA", "AO", "EH", "IH"],
    "o": ["AH", "OW", "AA", "AO", "UW", "UH", "W AH"], "u": ["AH", "UH", "UW", "Y UW", "IH", "Y AH", "W"],
    "i": ["IH", "AY", "IY", "AH", "Y"], "en": ["AH N"], "on": ["AH N"], "an": ["AH N"], "in": ["AH N"],
    "x": ["K S", "G Z", "Z", "K SH"], "ng": ["NG", "NG G", "NG K"], "n": ["AH N"], "ch": ["CH", "K", "SH"], "que": ["K"], "gue": ["G"], "ph": ["F"],
}
TABLE = {k: sorted(set(phonics.G.get(k, []) + EXTRA_G.get(k, []))) for k in {*phonics.G, *EXTRA_G}}
VOWEL_PHONES = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
LONG = {"EY", "IY", "AY", "OW", "UW", "Y UW"}

# Common irregular "heart" words: at most one of these is introduced per session.
HEART = set("""a the of to do does done said says was were what who whose where there their they you your
some come one once two gone have give live love move above could would should people friend friends again
any many busy eyes laugh enough through though thought tough rough young touch eight sure sugar island answer
often listen castle whistle women woman ocean school beautiful because colour color heart earth early learn
iron aunt half walk talk chalk buy build built bury blood floor door poor pretty sew shoe though truth
watch wash water want wear only both most other mother brother another nothing none won son ton front
monkey honey money oven glove shove month""".split())


def tokens(word: str) -> list[str]:
    return re.findall(r"[a-z']+", word.lower().replace("’", "'"))


def spell_pairs(tok: str, cmu: dict) -> list[tuple[str, str]] | None:
    """The word's (spelling, sound) pairs, e.g. cake -> c/K, a_e/EY, k/K. None if it can't be aligned."""
    phones = cmu.get(tok)
    if not phones:
        return None
    if "'" in tok:            # contractions: the apostrophe is silent
        tok = tok.replace("'", "")
    silent_e = False
    splits = phonics.align(tok, phones, TABLE)
    if not splits:
        # Endings on a magic-e word: waves = wave + s, smiled = smile + d.
        for end, sounds in (("s", ("S", "Z")), ("d", ("D", "T")), ("es", ("Z",))):
            if tok.endswith(end) and phones[-1] in sounds and tok[: -len(end)] not in ("",):
                base = spell_pairs_phones(tok[: -len(end)], phones[:-1])
                if base:
                    return base + [(end, phones[-1])]
    if not splits and tok.endswith("e"):
        splits, silent_e = phonics.align(tok[:-1], phones, TABLE), True
    if not splits:
        return None
    s = min(splits, key=lambda s: sum(g in phonics.RARE for g, _ in s))
    pairs = [(g, " ".join(p)) for g, p in s]
    if silent_e:
        # A final e makes the vowel before it long (a_e, i_e…); otherwise it rides on the consonant (-ce, -ve).
        for k in range(len(pairs) - 1, -1, -1):
            g, p = pairs[k]
            if len(g) == 1 and g in "aeiouy" and p in LONG:
                pairs[k] = (f"{g}_e", p)
                break
        else:
            g, p = pairs[-1]
            pairs[-1] = (g + "e", p)
    return pairs


def spell_pairs_phones(tok: str, phones: list[str]) -> list[tuple[str, str]] | None:
    return spell_pairs(tok, {tok: phones})


def syllables(tok: str, cmu: dict) -> int:
    phones = cmu.get(tok)
    if phones:
        return max(1, sum(p in VOWEL_PHONES for p in phones))
    return max(1, len(re.findall(r"[aeiouy]+", re.sub(r"e$", "", tok))))


def suffix_rules(tok: str, cmu: dict) -> int:
    """Suffix spelling rules the word needs: doubling (running), drop the e (making), y to i (cried).
    A rule counts only if the word sounds like its base plus the ending (so "singing" isn't "singe")."""
    phones = cmu.get(tok)
    if not phones:
        return 0
    def built_on(base):
        b = cmu.get(base)
        return bool(b) and phones[: len(b)] == b
    n = 0
    m = re.fullmatch(r"(.*([bdfgklmnprtvz]))\2(ing|ed|er|est|y)", tok)
    if m and built_on(m.group(1)):
        n += 1
    m = re.fullmatch(r"(.*[^aeiou])(ing|ed|er|est|able)", tok)
    if m and not re.search(r"(.)\1$", m.group(1)) and built_on(m.group(1) + "e"):
        n += 1
    m = re.fullmatch(r"(.*)i(es|ed|er|est|ly|ness|ful)", tok)
    if m and built_on(m.group(1) + "y"):
        n += 1
    return n


def spelling_stats(words: list[str], cmu: dict) -> dict:
    """How often each sound is spelled each way across the word list: {sound: {spelling: count}}."""
    counts = defaultdict(Counter)
    for w in words:
        for tok in tokens(w):
            for g, p in spell_pairs(tok, cmu) or []:
                counts[p][g] += 1
    return {p: dict(c) for p, c in counts.items()}


def surprise(g: str, p: str, stats: dict) -> float:
    """Bits of surprise for spelling sound p as g (smoothed)."""
    c = stats.get(p, {})
    total = sum(c.values())
    return -math.log2((c.get(g, 0) + 0.5) / (total + 0.5 * (len(c) + 1)))


def features(word: str, cmu: dict, stats: dict, grade: int | None, zipf: float | None) -> dict:
    toks = tokens(word)
    pairs, unaligned = [], 0
    for tok in toks:
        tp = spell_pairs(tok, cmu)
        if tp is None:
            unaligned += len(tok)
        else:
            pairs += tp
    bits = [(g, p, surprise(g, p, stats)) for g, p in pairs]
    total = sum(b for *_, b in bits) + unaligned * 1.3   # letters we couldn't match to sounds: irregular, so fairly hard
    # The pattern a word practises: its most surprising vowel spelling (or any spelling if no vowel is tricky).
    vowels = [b for b in bits if b[1].split()[0] in VOWEL_PHONES]
    key = max(vowels or bits, key=lambda b: b[2], default=None)
    return {
        "syllables": sum(syllables(t, cmu) for t in toks),
        "surprise": round(total, 2),
        "max_surprise": round(max((b for *_, b in bits), default=0), 2),
        "suffix": sum(suffix_rules(t, cmu) for t in toks),
        "letters": sum(len(t) for t in toks),
        "zipf": zipf,
        "grade": grade,
        "pattern": key[0] if key else None,
        "unaligned": unaligned > 0,
    }


def score(f: dict, weights: dict) -> float:
    rarity = max(0.0, 6.0 - (f["zipf"] if f["zipf"] is not None else 4.0))   # zipf 6+ = everyday word
    grade = (f["grade"] or 3) - 1
    return round(weights["syllables"] * (f["syllables"] - 1) + weights["surprise"] * f["surprise"]
                 + weights["suffix"] * f["suffix"] + weights["letters"] * f["letters"]
                 + weights["rarity"] * rarity + weights["grade"] * grade, 3)


def _zipf_lookup():
    try:
        from wordfreq import zipf_frequency
    except ImportError:
        return None
    return lambda word: min((zipf_frequency(t, "en") for t in tokens(word)), default=0.0)


def _grade(w: dict, tag_grades: dict) -> int | None:
    gs = [tag_grades[t] for t in w.get("tags", []) if t in tag_grades]
    return min(gs) if gs else None


def _homophones(words: dict, cmu: dict) -> dict[str, list[str]]:
    by_sound = defaultdict(list)
    for wid, w in words.items():
        toks = tokens(w["word"])
        if len(toks) == 1 and toks[0] in cmu:
            by_sound[" ".join(cmu[toks[0]])].append(wid)
    out = {}
    for ids in by_sound.values():
        spellings = {words[i]["word"].lower() for i in ids}
        if len(spellings) > 1:
            for i in ids:
                out[i] = [j for j in ids if words[j]["word"].lower() != words[i]["word"].lower()]
    return out


def _assign_order(words: dict) -> None:
    """Introduction order: level, then pattern groups (easiest group first), then score."""
    groups = defaultdict(list)
    for w in words.values():
        if w.get("rank"):
            groups[(w["rank"]["level"], w["rank"]["pattern"])].append(w["rank"]["score"])
    group_key = {k: sum(v) / len(v) for k, v in groups.items()}
    ranked = sorted((w for w in words.values() if w.get("rank")),
                    key=lambda w: (w["rank"]["level"], group_key[(w["rank"]["level"], w["rank"]["pattern"])],
                                   w["rank"]["pattern"] or "", w["rank"]["score"]))
    for i, w in enumerate(ranked):
        w["rank"]["order"] = i


def rank_all(store, settings: dict) -> dict:
    """(Re)rank every word. Returns a summary per level."""
    cfg = settings["ranking"]
    words = store.all_words()
    cmu = phonics.cmudict()
    stats = spelling_stats([w["word"] for w in words.values()], cmu)
    zipf = _zipf_lookup()
    scored = {}
    for wid, w in words.items():
        z = zipf(w["word"]) if zipf else (w.get("rank") or {}).get("features", {}).get("zipf")
        f = features(w["word"], cmu, stats, _grade(w, cfg["tag_grades"]), z)
        scored[wid] = (f, score(f, cfg["weights"]))
    values = sorted(s for _, s in scored.values())
    n = cfg["levels"]
    thresholds = [values[min(len(values) - 1, round(len(values) * k / n))] for k in range(1, n)]
    homo = _homophones(words, cmu)
    for wid, (f, s) in scored.items():
        _set_rank(words[wid], f, s, thresholds, homo.get(wid, []))
    _assign_order(words)
    store.put_words(list(words.values()))
    store.put_docs(RANKING, [{"id": "config", "stats": stats, "thresholds": thresholds, "zipf": zipf is not None}])
    return summary(words)


def rank_missing(store, settings: dict) -> int:
    """Rank words added since the last full ranking, reusing its statistics and level thresholds."""
    cfg = store.get_doc(RANKING, "config")
    words = store.all_words()
    todo = [w for w in words.values() if "computed_level" not in (w.get("rank") or {})]
    if not cfg or not todo:
        return 0
    cmu, zipf = phonics.cmudict(), _zipf_lookup()
    homo = _homophones(words, cmu)
    for w in todo:
        f = features(w["word"], cmu, cfg["stats"], _grade(w, settings["ranking"]["tag_grades"]),
                     zipf(w["word"]) if zipf else None)
        _set_rank(w, f, score(f, settings["ranking"]["weights"]), cfg["thresholds"], homo.get(w["id"], []))
    _assign_order(words)
    store.put_words(list(words.values()))
    return len(todo)


def _set_rank(w: dict, f: dict, s: float, thresholds: list, homophones: list) -> None:
    computed = bisect.bisect_right(thresholds, s) + 1
    override = (w.get("rank") or {}).get("override")
    w["rank"] = {"score": s, "level": override or computed, "computed_level": computed, "override": override,
                 "pattern": f["pattern"], "heart": w["word"].lower() in HEART or f["max_surprise"] >= 6.5,
                 "homophones": homophones, "features": f}


def set_override(w: dict, level: int | None) -> None:
    """A grown-up's level for this word (from the `level` column in `add`); None clears it."""
    r = w.setdefault("rank", {})
    r["override"] = level
    if "computed_level" in r:
        r["level"] = level or r["computed_level"]


def summary(words: dict) -> list[dict]:
    levels = defaultdict(list)
    for w in words.values():
        if w.get("rank"):
            levels[w["rank"]["level"]].append(w)
    out = []
    for lv in sorted(levels):
        ws = sorted(levels[lv], key=lambda w: w["rank"]["order"])
        out.append({"level": lv, "words": len(ws),
                    "syllables": round(sum(w["rank"]["features"]["syllables"] for w in ws) / len(ws), 2),
                    "examples": [w["word"] for w in ws[:: max(1, len(ws) // 8)]][:8]})
    return out
