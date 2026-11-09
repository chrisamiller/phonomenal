import difflib
import re

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'"})


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.translate(_APOSTROPHES)).strip()


def grade(typed: str, target: str, strict_case: bool = False) -> dict:
    """Compare an attempt to the target spelling.

    Returns correct/case_note plus `letters`: the target word split into
    characters, each marked ok=False where the child's attempt didn't match,
    so the UI can gently highlight just the tricky letters.
    """
    t, w = normalize(typed), normalize(target)
    exact = t == w
    loose = t.lower() == w.lower()
    correct = exact or (loose and not strict_case)
    case_note = None
    if loose and not exact:
        case_note = f"Remember: “{w}” is written with {'a capital' if w[:1].isupper() else 'a lowercase'} first letter."

    matcher = difflib.SequenceMatcher(None, t.lower(), w.lower(), autojunk=False)
    ok = [False] * len(w)
    for block in matcher.get_matching_blocks():
        for i in range(block.b, block.b + block.size):
            ok[i] = True
    letters = [{"ch": ch, "ok": ok[i]} for i, ch in enumerate(w)]
    return {"correct": correct, "word": w, "case_note": case_note, "letters": letters}
