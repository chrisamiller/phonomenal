"""Command-line tools for managing the word list.

  python -m app.cli import-anki anki_data/*.apkg
  python -m app.cli add words.csv            # columns: word, sentence, tags (sentence/tags optional)
  python -m app.cli export words.csv         # dump current words (e.g. to fill in sentences, then `add`)
  python -m app.cli remove-words Pam vim     # take words out (their past answers stay in the history)
  python -m app.cli audio-queue [--csv out.csv]   # what still needs (better) audio
  python -m app.cli generate-audio --engine google --limit 20   # work through the audio queue
  python -m app.cli tts-sample --voices Leda,Kore,Charon        # compare Google voices
  python -m app.cli prune-media [--delete]       # media files no word uses any more
  python -m app.cli import-prompts prompts.txt   # (re)load writing prompts
  python -m app.cli build-phonics                # letter-to-sound data for sound splitting
  python -m app.cli rank-words [--show 100]      # difficulty levels for introducing new words
  python -m app.cli build-sound-intros           # "The sound is /s/, as in sun" clips for sound match
  python -m app.cli export-backup [backup.json]  # everything, as one JSON file
  python -m app.cli restore-backup backup.json   # replace everything with a backup (asks first)
  python -m app.cli stats
  python -m app.cli master-known [--apply]  # quietly master words right (and easy) the first time
  python -m app.cli rename-tag OLD NEW [--apply]  # rename a tag on every word (update settings.toml too)

Set SPELLING_STORE=firestore to run any of these against Firestore instead of data/db.json.

Adding words or sentences never generates audio; it just joins the audio queue.
Until a clip exists, the app falls back to the browser's built-in voice.
"""
import argparse
import csv
import json
import shutil
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import phonics, ranking, tts, writing
from .anki import read_apkg, slug
from .config import DATA_DIR, load_settings
from .scheduler import current_day, new_meta, status, today, utcnow
from .store import LocalStore, check_dump, describe, open_store


def word_id(word: str) -> str:
    # Case matters for some words ("May" the month vs "may").
    return ("cap-" if word[:1].isupper() else "") + slug(word)


def new_word(word: str, tags: list[str]) -> dict:
    return {"id": word_id(word), "word": word, "sentence": "", "audio": None, "audio_source": None,
            "sentence_audio": None, "sentence_audio_source": None, "tags": tags, "added": utcnow().isoformat()}


def import_anki(store: LocalStore, paths: list[Path]) -> None:
    words = store.all_words()
    for path in paths:
        deck, entries, media = read_apkg(path)
        tag = slug(deck)
        added = merged = 0
        for e in entries:
            wid = word_id(e["word"])
            w = words.get(wid)
            if w:
                merged += 1
                if tag not in w["tags"]:
                    w["tags"].append(tag)
            else:
                w = words[wid] = new_word(e["word"], [tag])
                added += 1
            if not w["audio"] and e["audio"] in media:
                name = f"{wid}{Path(e['audio']).suffix.lower()}"
                store.save_media(name, media[e["audio"]])
                w["audio"], w["audio_source"] = name, "anki"
        print(f"{path.name}: deck '{deck}' (tag '{tag}'): {added} new, {merged} already present")
    store.put_words(list(words.values()))


def add_csv(store: LocalStore, path: Path) -> None:
    words = store.all_words()
    changed = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            text = (row.get("word") or "").strip()
            if not text:
                continue
            wid = word_id(text)
            w = words.get(wid) or new_word(text, [])
            tags = [t.strip() for t in (row.get("tags") or "").split(";") if t.strip()]
            w["tags"] = list(dict.fromkeys(w["tags"] + tags or [slug(path.stem)]))
            sentence = (row.get("sentence") or "").strip()
            if sentence and sentence != w["sentence"]:
                w["sentence"], w["sentence_audio"], w["sentence_audio_source"] = sentence, None, None
            level = (row.get("level") or "").strip()
            if level and int(level) != (w.get("rank") or {}).get("computed_level"):
                ranking.set_override(w, int(level))   # a grown-up's choice of level
            changed.append(w)
    store.put_words(changed)
    settings = load_settings()
    ranked = ranking.rank_missing(store, settings)
    queued = len(audio_queue(store.all_words(), settings, media_dir=store.media_dir))
    print(f"{len(changed)} words added/updated from {path.name} ({ranked} newly ranked); {queued} clips in the audio queue")


MIN_CLIP_BYTES = 500   # a real clip is several KB; anything this small is broken


def audio_queue(words: dict, settings: dict, also_replace=(), media_dir: Path | None = None) -> list[dict]:
    """Clips that are missing, broken (file gone or nearly empty), or made by an engine we want to replace."""
    replace = set(settings["audio"]["replace_sources"]) | set(also_replace)

    def reason(name, source):
        if not name:
            return "missing"
        if media_dir and (not (media_dir / name).exists() or (media_dir / name).stat().st_size < MIN_CLIP_BYTES):
            return "broken file"
        return f"replace {source}" if source in replace else None

    items = []
    for w in sorted(words.values(), key=lambda w: w["added"]):
        if r := reason(w["audio"], w.get("audio_source")):
            items.append({"id": w["id"], "kind": "word", "text": w["word"], "reason": r})
        if w["sentence"] and (r := reason(w["sentence_audio"], w.get("sentence_audio_source"))):
            items.append({"id": w["id"], "kind": "sentence", "text": w["sentence"], "reason": r})
    return items


def show_queue(store: LocalStore, out: Path | None) -> None:
    items = audio_queue(store.all_words(), load_settings(), media_dir=store.media_dir)
    for (kind, reason), n in sorted(Counter((i["kind"], i["reason"]) for i in items).items()):
        print(f"  {kind:9} {reason:20} {n}")
    print(f"{len(items)} clips queued")
    if out:
        with open(out, "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=["id", "kind", "text", "reason"])
            wr.writeheader()
            wr.writerows(items)
        print(f"wrote {out}")


def generate_audio(store: LocalStore, engine: str, voice: str | None, limit: int | None,
                   rate: float = 0.9, workers: int = 4, also_replace=()) -> None:
    if engine == "macos":
        if not tts.available():
            sys.exit("macOS `say` is not available")
        voice, ext, source, workers = voice or tts.DEFAULT_VOICE, "m4a", "macos-say", 1
        synth = lambda text: tts.synthesize(text, voice)
    else:
        from . import tts_google
        voice, ext, source = voice or tts_google.DEFAULT_VOICE, "chirp.mp3", tts_google.SOURCE
        synth = lambda text: tts_google.synthesize(text, voice, rate)
    items = audio_queue(store.all_words(), load_settings(), also_replace, store.media_dir)[:limit]
    print(f"{len(items)} clips to make with {voice} ({sum(len(i['text']) for i in items):,} characters)")

    def job(i):
        name = f"{i['id']}.sentence.{ext}" if i["kind"] == "sentence" else f"{i['id']}.{ext}"
        store.save_media(name, synth(i["text"]))
        return name

    pending, done, failed = [], 0, 0

    def save():
        # Saved in batches so an interrupted run keeps what it made; re-running picks up the rest.
        words = {}
        for i, name in pending:
            w = words.get(i["id"]) or store.get_word(i["id"])   # a word and its sentence can share a batch
            prefix = "sentence_audio" if i["kind"] == "sentence" else "audio"
            w[prefix], w[f"{prefix}_source"] = name, source
            words[w["id"]] = w
        store.put_words(list(words.values()))
        pending.clear()

    pool = ThreadPoolExecutor(workers)
    futures = {pool.submit(job, i): i for i in items}
    try:
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                pending.append((i, fut.result()))
                done += 1
                print(f"  [{done}/{len(items)}] {i['kind']}: {i['text']}")
            except Exception as e:  # keep going; failed clips stay in the queue
                failed += 1
                print(f"  FAILED {i['kind']} {i['id']}: {e}", file=sys.stderr)
            if len(pending) >= 25:
                save()
    except KeyboardInterrupt:
        print("stopping…")
        pool.shutdown(cancel_futures=True)
    finally:
        save()
        pool.shutdown()
    print(f"generated {done} clips" + (f"; {failed} failed (run again to retry)" if failed else ""))


def tts_sample(voices: list[str], texts: list[str], rate: float, out: Path, play: bool) -> None:
    """Write the same text in several Google voices so they can be compared by ear."""
    from . import tts_google
    out.mkdir(parents=True, exist_ok=True)
    for v in voices:
        name = v if "-" in v else f"en-US-Chirp3-HD-{v}"
        path = out / f"{name.rsplit('-', 1)[-1]}.mp3"
        path.write_bytes(b"".join(tts_google.synthesize(t, name, rate) for t in texts))
        print(f"  {path}")
        if play and shutil.which("afplay"):
            print(f"  playing {name}…")
            subprocess.run(["afplay", str(path)], check=False)


def prune_media(store: LocalStore, delete: bool) -> None:
    """Media files that no word points to (e.g. old clips replaced by a new voice)."""
    used = {n for w in store.all_words().values() for n in (w["audio"], w["sentence_audio"]) if n}
    unused = [p for p in sorted(store.media_dir.iterdir()) if p.is_file() and p.name not in used]
    size = sum(p.stat().st_size for p in unused)
    print(f"{len(unused)} unused media files ({size / 1e6:.1f} MB)")
    if delete:
        for p in unused:
            p.unlink()
        print("deleted")
    elif unused:
        print("  e.g. " + ", ".join(p.name for p in unused[:5]) + "\n  re-run with --delete to remove them")


def rank_words(store: LocalStore, show: int, csv_out: Path | None) -> None:
    settings = load_settings()
    levels = ranking.rank_all(store, settings)
    if not store.get_doc(ranking.RANKING, "config")["zipf"]:
        print("note: wordfreq isn't installed, so word frequency is left out "
              "(.venv/bin/pip install -r requirements-tools.txt)")
    for lv in levels:
        print(f"  level {lv['level']:2}: {lv['words']:4} words, {lv['syllables']} syllables avg  e.g. {', '.join(lv['examples'])}")
    words = sorted((w for w in store.all_words().values() if w.get("rank")), key=lambda w: w["rank"]["order"])
    if show:
        print(f"\nFirst {show} words in introduction order (before per-session rules):")
        print(", ".join(w["word"] for w in words[:show]))
    if csv_out:
        with open(csv_out, "w", newline="") as f:
            out = csv.writer(f)
            out.writerow(["order", "word", "level", "score", "pattern", "syllables", "surprise", "suffix_rules",
                          "zipf", "grade", "heart", "homophones"])
            for w in words:
                r, ft = w["rank"], w["rank"]["features"]
                out.writerow([r["order"] + 1, w["word"], r["level"], r["score"], r["pattern"], ft["syllables"],
                              ft["surprise"], ft["suffix"], ft["zipf"], ft["grade"], r["heart"],
                              ";".join(store.get_word(i)["word"] for i in r["homophones"])])
        print(f"wrote {csv_out}")


def export_backup(store: LocalStore, out: Path | None) -> Path:
    out = out or Path(f"spelling-backup-{today().isoformat()}.json")
    dump = store.dump()
    out.write_text(json.dumps(dump, ensure_ascii=False))
    print(f"wrote {out}: {describe(check_dump(dump))}")
    return out


def restore_backup(store: LocalStore, path: Path, yes: bool) -> None:
    """Replace everything in the store with a backup, after saving what's there now."""
    dump = check_dump(json.loads(path.read_text()))
    current = check_dump(store.dump())
    print(f"Restore into: {store.where()}")
    print(f"  now:    {describe(current)}")
    print(f"  backup: {describe(dump)}")
    if not yes and input("Replace everything with the backup? Type 'restore' to continue: ").strip() != "restore":
        sys.exit("cancelled; nothing changed")
    safety = store.data_dir / f"db.backup-before-restore-{utcnow().strftime('%Y%m%d-%H%M%S')}.json"
    safety.write_text(json.dumps(current, ensure_ascii=False))
    print(f"saved the current data to {safety} first")
    store.load_dump(dump)
    print(f"restored: {describe(check_dump(store.dump()))}")


def rename_tag(store: LocalStore, old: str, new: str, apply: bool) -> None:
    """Rename a tag on every word that has it. Without --apply, only reports what would change."""
    changed = []
    for w in store.all_words().values():
        if old in w["tags"]:
            w["tags"] = list(dict.fromkeys(new if t == old else t for t in w["tags"]))
            changed.append(w)
    print(f"{len(changed)} words tagged '{old}'" + ("" if apply else " (dry run: add --apply to rename)"))
    if apply and changed:
        store.put_words(changed)
        print(f"renamed to '{new}'")


def master_known(store: LocalStore, apply: bool) -> None:
    """Mark words that were right on their very first answer and rated easy as mastered, after the fact.

    Quiet: no credits, and they don't count toward achievements. Words missed since then are left alone.
    """
    words, progress = store.all_words(), store.all_progress()
    first = {}
    for r in store.reviews():
        if "correct" in r:
            first.setdefault(r["id"], r)
    picks, skipped = [], []
    for wid, r in first.items():
        p = progress.get(wid)
        if not (p and r["correct"] and r.get("rating") == "Easy") or p.get("retired"):
            continue
        if p["lapses"]:
            skipped.append(wid)
            continue
        picks.append({**p, "retired": True, "retired_at": r["ts"], "known_on_sight": True, "quiet": True})
    name = lambda wid: words.get(wid, {}).get("word", wid)
    print(f"{len(picks)} words to mark mastered: {', '.join(name(p['id']) for p in picks)}")
    if skipped:
        print(f"left alone (missed since): {', '.join(map(name, skipped))}")
    if apply:
        store.put_progress(picks)
        print("done")
    elif picks:
        print("dry run: add --apply to make the change")


def remove_words(store: LocalStore, names: list[str]) -> None:
    words = store.all_words()
    ids = [word_id(n) for n in names]
    missing = [n for n, i in zip(names, ids) if i not in words]
    found = [i for i in ids if i in words]
    store.delete_words(found)
    print(f"removed {len(found)} words" + (f"; not found: {', '.join(missing)}" if missing else "") +
          ". Their audio stays until `prune-media --delete`.")


def export_csv(store: LocalStore, path: Path) -> None:
    with open(path, "w", newline="") as f:
        out = csv.writer(f)
        out.writerow(["word", "sentence", "tags", "level"])
        for w in sorted(store.all_words().values(), key=lambda w: w["word"].lower()):
            out.writerow([w["word"], w["sentence"], ";".join(w["tags"]), (w.get("rank") or {}).get("level", "")])
    print(f"wrote {path}")


def stats(store: LocalStore) -> None:
    words, progress = store.all_words(), store.all_progress()
    meta = store.get_meta() or new_meta()
    now = current_day(meta, today())
    print(f"{len(words)} words; practice day {meta['practice_day']} (last practised {meta['last_practice_date'] or 'never'})")
    for k, v in sorted(Counter(status(progress.get(w), now) for w in words).items()):
        print(f"  {k:10} {v}")
    tags = Counter(t for w in words.values() for t in w["tags"])
    print("tags:", ", ".join(f"{t} ({n})" for t, n in tags.most_common()))
    print("word audio:", dict(Counter(w.get("audio_source") or "none" for w in words.values())))
    print(f"with sentence: {sum(1 for w in words.values() if w['sentence'])}, "
          f"audio queue: {len(audio_queue(words, load_settings(), media_dir=store.media_dir))}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("import-anki").add_argument("files", nargs="+", type=Path)
    sub.add_parser("add").add_argument("csv", type=Path)
    sub.add_parser("export").add_argument("csv", type=Path)
    sub.add_parser("remove-words").add_argument("words", nargs="+")
    sub.add_parser("audio-queue").add_argument("--csv", type=Path)
    p = sub.add_parser("generate-audio")
    p.add_argument("--engine", required=True, choices=["macos", "google"])
    p.add_argument("--voice", help="e.g. Samantha (macos) or en-US-Chirp3-HD-Leda (google)")
    p.add_argument("--rate", type=float, default=0.9, help="google speaking rate (1.0 = normal)")
    p.add_argument("--workers", type=int, default=4, help="parallel google requests")
    p.add_argument("--limit", type=int)
    p.add_argument("--replace", action="append", default=[], metavar="SOURCE",
                   help="also redo clips from this source, e.g. --replace anki for one consistent voice")
    p = sub.add_parser("tts-sample")
    p.add_argument("--voices", default="Leda,Kore,Aoede,Achernar,Charon,Puck")
    p.add_argument("--text", action="append", help="repeatable; defaults to a word and a sentence")
    p.add_argument("--rate", type=float, default=0.9)
    p.add_argument("--out", type=Path, default=Path("tts_samples"))
    p.add_argument("--play", action="store_true", help="play each sample (macOS)")
    sub.add_parser("prune-media").add_argument("--delete", action="store_true")
    sub.add_parser("import-prompts").add_argument("file", type=Path)
    sub.add_parser("build-phonics")
    p = sub.add_parser("build-sound-intros")
    p.add_argument("--voice", default="en-US-Chirp3-HD-Leda")
    p.add_argument("--rate", type=float, default=0.85)
    p.add_argument("--sound", action="append", help="only these sound ids (repeatable), e.g. --sound s")
    p = sub.add_parser("rank-words")
    p.add_argument("--show", type=int, default=100, help="print this many words in introduction order")
    p.add_argument("--csv", type=Path, help="write every word's level, score and features")
    sub.add_parser("stats")
    sub.add_parser("master-known").add_argument("--apply", action="store_true")
    p = sub.add_parser("rename-tag")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--apply", action="store_true")
    sub.add_parser("export-backup").add_argument("out", type=Path, nargs="?")
    p = sub.add_parser("restore-backup")
    p.add_argument("file", type=Path)
    p.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = ap.parse_args(argv)

    store = open_store()
    if args.cmd == "import-anki":
        import_anki(store, args.files)
    elif args.cmd == "add":
        add_csv(store, args.csv)
    elif args.cmd == "export":
        export_csv(store, args.csv)
    elif args.cmd == "audio-queue":
        show_queue(store, args.csv)
    elif args.cmd == "import-prompts":
        new, total = writing.import_prompts(store, args.file)
        print(f"{new} new prompts; {total} approved in total")
    elif args.cmd == "remove-words":
        remove_words(store, args.words)
    elif args.cmd == "master-known":
        master_known(store, args.apply)
    elif args.cmd == "rename-tag":
        rename_tag(store, args.old, args.new, args.apply)
    elif args.cmd == "export-backup":
        export_backup(store, args.out)
    elif args.cmd == "restore-backup":
        restore_backup(store, args.file, args.yes)
    elif args.cmd == "build-phonics":
        print(phonics.build(store))
    elif args.cmd == "build-sound-intros":
        from . import sound_intros
        print(f"wrote {sound_intros.build(args.voice, args.rate, args.sound)} clips to {sound_intros.INTRO_DIR}")
    elif args.cmd == "rank-words":
        rank_words(store, args.show, args.csv)
    elif args.cmd == "generate-audio":
        generate_audio(store, args.engine, args.voice, args.limit, args.rate, args.workers, args.replace)
    elif args.cmd == "tts-sample":
        texts = args.text or ["necessary", "We packed everything we needed for the long trip."]
        tts_sample([v.strip() for v in args.voices.split(",")], texts, args.rate, args.out, args.play)
    elif args.cmd == "prune-media":
        prune_media(store, args.delete)
    else:
        stats(store)


if __name__ == "__main__":
    sys.exit(main())
