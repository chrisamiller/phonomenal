"""Persistence layer.

Everything the app stores goes through a store. `LocalStore` keeps metadata in a
single JSON file; `FirestoreStore` keeps it in Firestore (used on Cloud Run, see
docs/deploy-gcp.md). Both keep audio in a local media folder (on Cloud Run, a mounted
Cloud Storage bucket). `open_store()` picks one from SPELLING_STORE ("local" or "firestore").

A backup ("dump") of either store is the same JSON as data/db.json, so a backup from the
cloud can be opened locally and restored into either store (`restore-backup`).

Data shapes:
  word:     {id, word, sentence, audio, sentence_audio, tags, added}
  progress: {id, card (fsrs dict; dates on the practice-day clock), reps, lapses,
             streak, retired, retired_at, first_review_day, last_review_day, last_review}
  review:   {id, ts, day, typed, correct, rating, spot_check}
  meta:     {practice_day, last_practice_date, return_day, counters}

Other features use two generic shapes, so a cloud store maps them directly to
collections:
  docs(coll)    keyed documents, e.g. missions (by date), prompts, projects, achievements
  records(coll) append-only logs, e.g. ledger, writing responses, split results
"""
import copy
import json
import os
import secrets
import threading
import time
from pathlib import Path

from . import config

EMPTY = {"version": 1, "words": {}, "progress": {}, "reviews": [], "meta": {}, "docs": {}, "logs": {}}


def open_store():
    """The store chosen by SPELLING_STORE: "local" (data/db.json, the default) or "firestore"."""
    if os.environ.get("SPELLING_STORE", "local") == "firestore":
        try:
            from google.cloud import firestore
        except ImportError:
            raise SystemExit("google-cloud-firestore is not installed: .venv/bin/pip install -r requirements-cloud.txt")
        client = firestore.Client(project=os.environ.get("SPELLING_FIRESTORE_PROJECT") or None,
                                  database=os.environ.get("SPELLING_FIRESTORE_DATABASE", "(default)"))
        return FirestoreStore(client, config.DATA_DIR)
    return LocalStore(config.DATA_DIR)   # looked up now, not at import, so tests can point it elsewhere


def check_dump(dump: dict) -> dict:
    """A complete, valid backup (missing sections become empty)."""
    if not isinstance(dump, dict) or not isinstance(dump.get("words"), dict):
        raise ValueError("this doesn't look like a spelling backup (no words)")
    out = copy.deepcopy(EMPTY)
    out.update({k: v for k, v in dump.items() if k in EMPTY})
    return out


def describe(dump: dict) -> str:
    return (f"{len(dump['words'])} words, {len(dump['progress'])} with progress, {len(dump['reviews'])} answers, "
            f"{sum(len(v) for v in dump['logs'].values())} log records, practice day {dump['meta'].get('practice_day', 0)}")


class LocalStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.media_dir = self.data_dir / "media"
        self.db_path = self.data_dir / "db.json"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._mtime = None
        self._db = self._load()

    def _load(self) -> dict:
        if self.db_path.exists():
            self._mtime = self.db_path.stat().st_mtime_ns
            return json.loads(self.db_path.read_text())
        return copy.deepcopy(EMPTY)

    def _fresh(self) -> dict:
        """Reload if another process (e.g. the CLI adding words) changed the file."""
        if self.db_path.exists() and self.db_path.stat().st_mtime_ns != self._mtime:
            self._db = self._load()
        return self._db

    def _flush(self) -> None:
        tmp = self.db_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._db, indent=1, ensure_ascii=False))
        os.replace(tmp, self.db_path)
        self._mtime = self.db_path.stat().st_mtime_ns

    # --- words ---
    def all_words(self) -> dict[str, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._fresh()["words"].items()}

    def get_word(self, word_id: str) -> dict | None:
        with self._lock:
            w = self._fresh()["words"].get(word_id)
            return dict(w) if w else None

    def put_words(self, words: list[dict]) -> None:
        with self._lock:
            for w in words:
                self._fresh()["words"][w["id"]] = w
            self._flush()

    def delete_words(self, word_ids: list[str]) -> None:
        """Remove words and their progress (past answers stay in the review log)."""
        with self._lock:
            for i in word_ids:
                self._fresh()["words"].pop(i, None)
                self._fresh()["progress"].pop(i, None)
            self._flush()

    # --- progress ---
    def all_progress(self) -> dict[str, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._fresh()["progress"].items()}

    def get_progress(self, word_id: str) -> dict | None:
        with self._lock:
            p = self._fresh()["progress"].get(word_id)
            return dict(p) if p else None

    def put_progress(self, progress: list[dict]) -> None:
        """Change progress records directly (no answer logged), e.g. for one-off fixes."""
        with self._lock:
            for p in progress:
                self._fresh()["progress"][p["id"]] = p
            self._flush()

    def save_review(self, progress: dict, review: dict) -> None:
        """Atomically update a word's progress and append to the review log."""
        with self._lock:
            self._fresh()["progress"][progress["id"]] = progress
            self._fresh()["reviews"].append(review)
            self._flush()

    def reviews(self) -> list[dict]:
        with self._lock:
            return list(self._fresh()["reviews"])

    # --- meta (practice-day clock) ---
    def get_meta(self) -> dict:
        with self._lock:
            return dict(self._fresh().get("meta") or {})

    def put_meta(self, meta: dict) -> None:
        with self._lock:
            self._fresh()["meta"] = meta
            self._flush()

    # --- generic keyed documents and append-only logs ---
    def docs(self, coll: str) -> dict[str, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._fresh().get("docs", {}).get(coll, {}).items()}

    def get_doc(self, coll: str, doc_id: str) -> dict | None:
        with self._lock:
            d = self._fresh().get("docs", {}).get(coll, {}).get(doc_id)
            return dict(d) if d else None

    def put_docs(self, coll: str, docs: list[dict]) -> None:
        with self._lock:
            c = self._fresh().setdefault("docs", {}).setdefault(coll, {})
            for d in docs:
                c[d["id"]] = d
            self._flush()

    def records(self, coll: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._fresh().get("logs", {}).get(coll, [])]

    def append(self, coll: str, recs: list[dict]) -> None:
        with self._lock:
            self._fresh().setdefault("logs", {}).setdefault(coll, []).extend(recs)
            self._flush()

    # --- backups ---
    def dump(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._fresh())

    def load_dump(self, dump: dict) -> None:
        """Replace everything with a backup."""
        with self._lock:
            self._db = check_dump(dump)
            self._flush()

    def where(self) -> str:
        return str(self.db_path)

    # --- media ---
    def save_media(self, name: str, data: bytes) -> None:
        (self.media_dir / name).write_bytes(data)

    def has_media(self, name: str) -> bool:
        return (self.media_dir / name).exists()

    def media_url(self, name: str | None) -> str | None:
        return f"/media/{name}" if name else None


class FirestoreStore(LocalStore):
    """The same methods as LocalStore, backed by Firestore.

    Collections: words, progress, reviews, meta (one document), docs__<name> for keyed documents
    and log__<name> for append-only logs. Each document holds one record as JSON text in field
    "j", which keeps every record exactly as it is locally (Firestore can't store lists of lists).

    Each collection is cached in memory with a version token in _versions/<collection>. Every write
    sets a new token, so changes from another process (the CLI on your Mac) show up on the next read,
    and a page load costs one small read per collection instead of reading everything again.
    """
    VERSIONS = "_versions"
    BATCH = 400   # Firestore allows 500 writes per batch

    def __init__(self, client, data_dir: Path):
        self.client = client
        self.data_dir = Path(data_dir)
        self.media_dir = self.data_dir / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cache = {}   # collection -> (token, {doc id: record})

    # --- plumbing ---
    def _token(self, coll: str):
        snap = self.client.collection(self.VERSIONS).document(coll).get()
        return snap.to_dict().get("t") if snap.exists else None

    def _coll(self, coll: str) -> dict:
        """All records in a collection, keyed by document id (cached; refreshed when the token changes)."""
        with self._lock:
            token = self._token(coll)
            cached = self._cache.get(coll)
            if cached and cached[0] == token:
                return cached[1]
            data = {s.id: json.loads(s.to_dict()["j"]) for s in self.client.collection(coll).stream()}
            self._cache[coll] = (token, data)
            return data

    def _write(self, coll: str, records: dict[str, dict] | None = None, deletes=()) -> None:
        with self._lock:
            data = self._coll(coll)
            ops = [("set", i, r) for i, r in (records or {}).items()] + [("delete", i, None) for i in deletes]
            token = secrets.token_hex(8)
            for start in range(0, max(1, len(ops)), self.BATCH):
                batch = self.client.batch()
                for op, i, r in ops[start:start + self.BATCH]:
                    ref = self.client.collection(coll).document(i)
                    if op == "set":
                        batch.set(ref, {"j": json.dumps(r, ensure_ascii=False)})
                    else:
                        batch.delete(ref)
                if start + self.BATCH >= len(ops):   # the token goes with the last batch
                    batch.set(self.client.collection(self.VERSIONS).document(coll), {"t": token})
                batch.commit()
            for op, i, r in ops:
                if op == "set":
                    data[i] = r
                else:
                    data.pop(i, None)
            self._cache[coll] = (token, data)

    @staticmethod
    def _seq_ids(n: int) -> list[str]:
        """Ids that sort in insertion order, for append-only logs."""
        base = time.time_ns()
        return [f"{base + k:020d}-{secrets.token_hex(3)}" for k in range(n)]

    def _log(self, coll: str) -> list[dict]:
        data = self._coll(coll)
        return [data[k] for k in sorted(data)]

    # --- words and progress ---
    def all_words(self) -> dict[str, dict]:
        return {k: dict(v) for k, v in self._coll("words").items()}

    def get_word(self, word_id: str) -> dict | None:
        w = self._coll("words").get(word_id)
        return dict(w) if w else None

    def put_words(self, words: list[dict]) -> None:
        self._write("words", {w["id"]: w for w in words})

    def delete_words(self, word_ids: list[str]) -> None:
        with self._lock:
            self._write("words", deletes=[i for i in word_ids if i in self._coll("words")])
            self._write("progress", deletes=[i for i in word_ids if i in self._coll("progress")])

    def all_progress(self) -> dict[str, dict]:
        return {k: dict(v) for k, v in self._coll("progress").items()}

    def get_progress(self, word_id: str) -> dict | None:
        p = self._coll("progress").get(word_id)
        return dict(p) if p else None

    def put_progress(self, progress: list[dict]) -> None:
        self._write("progress", {p["id"]: p for p in progress})

    def save_review(self, progress: dict, review: dict) -> None:
        with self._lock:
            self._write("progress", {progress["id"]: progress})
            self._write("reviews", dict(zip(self._seq_ids(1), [review])))

    def reviews(self) -> list[dict]:
        return [dict(r) for r in self._log("reviews")]

    # --- meta ---
    def get_meta(self) -> dict:
        return dict(self._coll("meta").get("meta") or {})

    def put_meta(self, meta: dict) -> None:
        self._write("meta", {"meta": meta})

    # --- generic documents and logs ---
    def docs(self, coll: str) -> dict[str, dict]:
        return {k: dict(v) for k, v in self._coll(f"docs__{coll}").items()}

    def get_doc(self, coll: str, doc_id: str) -> dict | None:
        d = self._coll(f"docs__{coll}").get(doc_id)
        return dict(d) if d else None

    def put_docs(self, coll: str, docs: list[dict]) -> None:
        self._write(f"docs__{coll}", {d["id"]: d for d in docs})

    def records(self, coll: str) -> list[dict]:
        return [dict(r) for r in self._log(f"log__{coll}")]

    def append(self, coll: str, recs: list[dict]) -> None:
        self._write(f"log__{coll}", dict(zip(self._seq_ids(len(recs)), recs)))

    # --- backups ---
    def _collection_names(self) -> list[str]:
        return [c.id for c in self.client.collections()]

    def dump(self) -> dict:
        names = self._collection_names()
        return {
            "version": 1, "words": self.all_words(), "progress": self.all_progress(), "reviews": self.reviews(),
            "meta": self.get_meta(),
            "docs": {n[len("docs__"):]: self.docs(n[len("docs__"):]) for n in names if n.startswith("docs__")},
            "logs": {n[len("log__"):]: self.records(n[len("log__"):]) for n in names if n.startswith("log__")},
        }

    def load_dump(self, dump: dict) -> None:
        """Replace everything with a backup: every collection is emptied, then refilled."""
        dump = check_dump(dump)
        with self._lock:
            for name in self._collection_names():
                if name != self.VERSIONS:
                    self._write(name, deletes=list(self._coll(name)))
            seq = lambda recs: {f"{k:020d}": r for k, r in enumerate(recs)}   # keeps their order
            self._write("words", dump["words"])
            self._write("progress", dump["progress"])
            self._write("reviews", seq(dump["reviews"]))
            self._write("meta", {"meta": dump["meta"]})
            for coll, docs in dump["docs"].items():
                self._write(f"docs__{coll}", docs)
            for coll, recs in dump["logs"].items():
                self._write(f"log__{coll}", seq(recs))

    def where(self) -> str:
        return f"Firestore project {self.client.project}, database {getattr(self.client, '_database', '(default)')}"
