"""Letter-to-sound alignment for the sound-splitting (and later sound-match) games.

Pronunciations come from the CMU Pronouncing Dictionary (data/phonics/cmudict.dict,
BSD licence). The aligner splits a word into graphemes (letter groups) using the table
below, constrained to match the dictionary's phonemes exactly.

Conventions (agreed): digraphs, vowel teams, r-controlled vowels, double letters and
silent-letter pairs (kn, wr, mb) are one sound; x, qu and nk are one sound; blends stay
separate; words with a silent final e are excluded; multi-syllable words are excluded for now.
"""
import random
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from .config import DATA_DIR

CMUDICT = DATA_DIR / "phonics" / "cmudict.dict"

# grapheme -> allowed phoneme sequences (ARPAbet without stress digits)
G = {
    # consonants
    "b": ["B"], "bb": ["B"], "c": ["K", "S"], "cc": ["K"], "ck": ["K"], "ch": ["CH", "K", "SH"],
    "d": ["D"], "dd": ["D"], "dge": ["JH"], "f": ["F"], "ff": ["F"], "g": ["G", "JH"], "gg": ["G"],
    "gh": ["G", "F"], "gu": ["G"], "gn": ["N"], "h": ["HH"], "j": ["JH"], "k": ["K"], "kn": ["N"],
    "l": ["L"], "ll": ["L"], "m": ["M"], "mm": ["M"], "mb": ["M"], "n": ["N", "NG"], "nn": ["N"],
    "ng": ["NG"], "nk": ["NG K"], "p": ["P"], "pp": ["P"], "ph": ["F"], "qu": ["K W", "K"], "r": ["R"], "rr": ["R"],
    "s": ["S", "Z"], "ss": ["S"], "sh": ["SH"], "t": ["T"], "tt": ["T"], "tch": ["CH"],
    "th": ["TH", "DH"], "v": ["V"], "w": ["W"], "wh": ["W", "HH"], "wr": ["R"],
    "x": ["K S", "G Z", "Z"], "y": ["Y"], "z": ["Z"], "zz": ["Z"],
    # single vowels
    "a": ["AE", "EY", "AA", "AH", "AO", "EH"], "e": ["EH", "IY", "AH", "IH"],
    "i": ["IH", "AY", "IY", "AH"], "o": ["AA", "OW", "AH", "AO", "UW", "UH"],
    "u": ["AH", "UH", "UW", "Y UW", "IH"], "y_v": ["IY", "AY", "IH"],
    # vowel teams
    "ai": ["EY", "EH"], "ay": ["EY"], "ee": ["IY"], "ea": ["IY", "EH", "EY"], "ie": ["AY", "IY"],
    "igh": ["AY"], "oa": ["OW"], "oe": ["OW", "UW"], "ow": ["OW", "AW"], "ou": ["AW", "UW", "AH", "OW"],
    "ough": ["AO", "AA", "OW", "UW", "AW"], "oi": ["OY"], "oy": ["OY"], "oo": ["UW", "UH", "AH"],
    "ew": ["UW", "Y UW"], "ue": ["UW", "Y UW"], "ui": ["UW", "IH"], "au": ["AO", "AA", "AE"], "aigh": ["EY"],
    "aw": ["AO", "AA"], "augh": ["AO", "AA"], "ei": ["EY", "IY"], "eigh": ["EY"], "ey": ["IY", "EY"],
    "al": ["AO", "AA", "AE"], "oul": ["UH"],
    # r-controlled
    "ar": ["AA R", "AO R", "EH R"], "or": ["AO R", "ER"], "oor": ["AO R"], "ed": ["T", "D"], "er": ["ER"], "ir": ["ER"], "ur": ["ER"], "ear": ["IH R", "IY R", "ER", "EH R", "AA R"],
    "air": ["EH R", "EY R"], "oar": ["AO R"], "our": ["AW R", "AO R", "UH R", "ER"], "eer": ["IH R", "IY R"],
}
# Rarer spellings lose ties, so "ball" is b|a|ll rather than b|al|l.
RARE = {"al", "oul", "gu", "gh", "ed"}
VOWEL_TEAMS = {"aigh", "ai", "ay", "ee", "ea", "ie", "igh", "oa", "oe", "ow", "ou", "ough", "oi", "oy", "oo",
               "ew", "ue", "ui", "au", "aw", "augh", "ei", "eigh", "ey"}


@lru_cache(maxsize=1)
def cmudict() -> dict[str, list[str]]:
    out = {}
    for line in Path(CMUDICT).read_text(encoding="latin-1").splitlines():
        if not line or line.startswith(";;;"):
            continue
        word, *phones = line.split("#")[0].split()
        if "(" not in word:  # first pronunciation only
            out[word] = [re.sub(r"\d", "", p) for p in phones]
    return out


def _options(word: str, i: int, table: dict):
    """Graphemes that can start at letter i, with their phoneme options."""
    for n in range(min(max(len(g) for g in table), len(word) - i), 0, -1):
        g = word[i:i + n]
        key = "y_v" if g == "y" else g
        if key in table:
            yield g, [p.split() for p in table[key]] + ([["Y"]] if g == "y" else [])


def align(word: str, phones: list[str], table: dict = G) -> list[list[tuple[str, tuple]]]:
    """All minimal-length grapheme splits of `word` matching `phones` exactly.
    `table` lets the difficulty ranking add multi-syllable spellings (-tion, -le) the games don't use."""
    @lru_cache(maxsize=None)
    def go(i: int, j: int):
        if i == len(word):
            return [[]] if j == len(phones) else []
        results = []
        for g, opts in _options(word, i, table):
            for seq in opts:
                if phones[j:j + len(seq)] == seq:
                    for rest in go(i + len(g), j + len(seq)):
                        results.append([(g, tuple(seq))] + rest)
        if not results:
            return []
        best = min(len(r) for r in results)
        return [r for r in results if len(r) == best]
    return go(0, 0)


def analyse(word: str) -> dict:
    if not re.fullmatch(r"[a-z]+", word):
        return {"status": "excluded", "reason": "not a plain lowercase word"}
    phones = cmudict().get(word)
    if not phones:
        return {"status": "excluded", "reason": "not in pronouncing dictionary"}
    vowels = sum(1 for p in phones if p[:2] in {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY",
                                               "IH", "IY", "OW", "OY", "UH", "UW"})
    if vowels != 1:
        return {"status": "excluded", "reason": f"{vowels} syllables"}
    if re.search(r"[aeiouy][^aeiouy]ed$", word) and analyse(word[:-1]).get("reason") == "silent e":
        return {"status": "excluded", "reason": "silent e"}  # smiled = smile + d
    splits = align(word, phones)
    if not splits:
        # No grapheme spells a silent final e, so silent-e words land here.
        reason = "silent e" if word.endswith("e") else "no alignment"
        return {"status": "excluded", "reason": reason, "phonemes": phones}
    fewest_rare = min(sum(g in RARE for g, _ in s) for s in splits)
    splits = [s for s in splits if sum(g in RARE for g, _ in s) == fewest_rare]
    distinct = {tuple(g for g, _ in s) for s in splits}
    s = splits[0]
    return {
        "status": "ok" if len(distinct) == 1 else "ambiguous",
        "reason": None if len(distinct) == 1 else "splits: " + " / ".join("|".join(d) for d in sorted(distinct)),
        "graphemes": [g for g, _ in s], "phonemes": [list(p) for _, p in s],
    }


def build(store) -> dict:
    """Analyse every word and store the result on the word record."""
    words = store.all_words()
    counts = defaultdict(int)
    for w in words.values():
        w["phonics"] = analyse(w["word"])
        counts[w["phonics"]["status"]] += 1
    store.put_words(list(words.values()))
    return dict(counts)


def boundaries(graphemes: list[str]) -> list[int]:
    """Letter positions where a divider goes (after letter k)."""
    out, pos = [], 0
    for g in graphemes[:-1]:
        pos += len(g)
        out.append(pos)
    return out


def pick_session(store, n: int, rng=random) -> list[dict]:
    """Words for one session, weighted toward grapheme patterns she gets wrong."""
    words = [w for w in store.all_words().values() if (w.get("phonics") or {}).get("status") == "ok"]
    results = store.records("split_results")
    tally = defaultdict(lambda: [0, 0])
    recent = {r["word_id"] for r in results[-60:]}
    for r in results:
        for g in r["graphemes"]:
            if len(g) > 1:
                tally[g][0] += r["split_ok"]
                tally[g][1] += 1

    def weight(w):
        gs = [g for g in w["phonics"]["graphemes"] if len(g) > 1]
        wt = 1.0
        for g in gs:
            ok, total = tally[g]
            wt += 2.0 if total == 0 else 3.0 * (1 - ok / total)
        return wt * (0.2 if w["id"] in recent else 1.0)

    chosen = []
    pool = list(words)
    for _ in range(min(n, len(pool))):
        w = rng.choices(pool, weights=[weight(x) for x in pool])[0]
        pool.remove(w)
        chosen.append(w)
    return [{"id": w["id"], "word": w["word"]} for w in chosen]


def check(word: dict, count_answer: int, split_answer: list[int]) -> dict:
    gs = word["phonics"]["graphemes"]
    return {
        "count_ok": count_answer == len(gs), "count": len(gs),
        "split_ok": sorted(split_answer) == boundaries(gs), "graphemes": gs,
        "boundaries": boundaries(gs), "vowel_team": any(g in VOWEL_TEAMS for g in gs),
    }
