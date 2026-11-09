"""The same behaviour from LocalStore and FirestoreStore (against an in-memory stand-in for Firestore)."""
import importlib
import json

import pytest
from fastapi.testclient import TestClient

from app.store import FirestoreStore, LocalStore, check_dump


class FakeSnap:
    def __init__(self, id, data):
        self.id, self._data = id, data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeDoc:
    def __init__(self, db, coll, id):
        self.db, self.coll, self.id = db, coll, id

    def get(self):
        self.db.reads += 1
        return FakeSnap(self.id, self.db.data.get(self.coll, {}).get(self.id))


class FakeColl:
    def __init__(self, db, id):
        self.db, self.id = db, id

    def document(self, id):
        return FakeDoc(self.db, self.id, id)

    def stream(self):
        docs = self.db.data.get(self.id, {})
        self.db.reads += len(docs)
        return [FakeSnap(k, v) for k, v in sorted(docs.items())]


class FakeBatch:
    def __init__(self, db):
        self.db, self.ops = db, []

    def set(self, ref, data):
        self.ops.append((ref, data))

    def delete(self, ref):
        self.ops.append((ref, None))

    def commit(self):
        assert len(self.ops) <= 500, "Firestore allows 500 writes per batch"
        for ref, data in self.ops:
            coll = self.db.data.setdefault(ref.coll, {})
            if data is None:
                coll.pop(ref.id, None)
            else:
                assert all(not isinstance(v, (list, dict)) for v in data.values())
                coll[ref.id] = dict(data)
        self.db.data = {k: v for k, v in self.db.data.items() if v}


class FakeFirestore:
    project = "test-project"

    def __init__(self):
        self.data, self.reads = {}, 0

    def collection(self, id):
        return FakeColl(self, id)

    def collections(self):
        return [FakeColl(self, k) for k in self.data]

    def batch(self):
        return FakeBatch(self)


@pytest.fixture(params=["local", "firestore"])
def store(request, tmp_path):
    return LocalStore(tmp_path) if request.param == "local" else FirestoreStore(FakeFirestore(), tmp_path)


def test_store_contract(store):
    store.put_words([{"id": "cat", "word": "cat", "phonics": {"phonemes": [["K"], ["AE"], ["T"]]}}])
    assert store.get_word("cat")["phonics"]["phonemes"] == [["K"], ["AE"], ["T"]]   # lists of lists survive
    store.save_review({"id": "cat", "streak": 1}, {"id": "cat", "correct": True})
    store.save_review({"id": "cat", "streak": 2}, {"id": "cat", "correct": True, "n": 2})
    assert store.get_progress("cat")["streak"] == 2 and [r.get("n") for r in store.reviews()] == [None, 2]
    store.put_meta({"practice_day": 3})
    assert store.get_meta() == {"practice_day": 3}
    store.put_docs("missions", [{"id": "2026-10-31", "done": {}}])
    assert store.get_doc("missions", "2026-10-31") == {"id": "2026-10-31", "done": {}} and store.docs("nope") == {}
    store.append("ledger", [{"amount": 10}, {"amount": -5}])
    store.append("ledger", [{"amount": 1}])
    assert [r["amount"] for r in store.records("ledger")] == [10, -5, 1]
    store.put_words([{"id": "dog", "word": "dog"}])
    store.delete_words(["dog", "nope"])
    assert store.get_word("dog") is None and store.get_word("cat")
    # Copies, not the stored objects.
    store.get_word("cat")["word"] = "dog"
    assert store.get_word("cat")["word"] == "cat"


def test_backup_round_trip_between_stores(tmp_path):
    local = LocalStore(tmp_path / "a")
    local.put_words([{"id": f"w{i}", "word": f"w{i}"} for i in range(900)])   # more than one Firestore batch
    local.save_review({"id": "w1", "streak": 1}, {"id": "w1", "correct": True})
    local.put_meta({"practice_day": 5})
    local.put_docs("missions", [{"id": "d1"}])
    local.append("ledger", [{"amount": a} for a in (3, 1, 2)])
    cloud = FirestoreStore(FakeFirestore(), tmp_path / "b")
    cloud.put_docs("stale", [{"id": "old"}])
    cloud.load_dump(local.dump())
    assert cloud.docs("stale") == {}                          # restore replaces everything
    assert check_dump(cloud.dump()) == check_dump(local.dump())
    assert [r["amount"] for r in cloud.records("ledger")] == [3, 1, 2]
    cloud.append("ledger", [{"amount": 9}])                   # new records sort after restored ones
    assert [r["amount"] for r in cloud.records("ledger")] == [3, 1, 2, 9]
    back = LocalStore(tmp_path / "c")
    back.load_dump(cloud.dump())
    assert back.dump()["logs"]["ledger"][-1] == {"amount": 9}


def test_firestore_cache_sees_other_processes(tmp_path):
    db = FakeFirestore()
    server, cli = FirestoreStore(db, tmp_path), FirestoreStore(db, tmp_path)
    server.put_words([{"id": "a", "word": "a"}])
    assert set(server.all_words()) == {"a"}
    reads = db.reads
    server.all_words()
    assert db.reads - reads == 1                              # cached: just the version check
    cli.put_words([{"id": "b", "word": "b"}])                 # e.g. `add` run from the Mac
    assert set(server.all_words()) == {"a", "b"}


def test_backup_download_and_cli_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("SPELLING_DATA_DIR", str(tmp_path))
    import app.config
    importlib.reload(app.config)
    main = importlib.reload(importlib.import_module("app.main"))
    main.store.put_words([{"id": "cat", "word": "cat"}])
    main.store.append("ledger", [{"amount": 7}])
    r = TestClient(main.app).get("/api/backup")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    backup = tmp_path / "backup.json"
    backup.write_text(r.text)

    main.store.put_words([{"id": "dog", "word": "dog"}])
    from app import cli
    cli.restore_backup(main.store, backup, yes=True)
    assert set(main.store.all_words()) == {"cat"} and main.store.records("ledger") == [{"amount": 7}]
    saved = list(tmp_path.glob("db.backup-before-restore-*.json"))
    assert len(saved) == 1 and "dog" in json.loads(saved[0].read_text())["words"]
    with pytest.raises(ValueError):
        check_dump({"not": "a backup"})
