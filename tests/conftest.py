"""Tests never touch the real data folder: everything starts in a throwaway one.

This runs before any app module is imported, so even a test that forgets to set up its own
folder writes to the throwaway one. The pronouncing dictionary is linked in read-only.
"""
import os
import tempfile
from pathlib import Path

import pytest

_REAL = Path(__file__).resolve().parent.parent / "data"
_TMP = Path(tempfile.mkdtemp(prefix="spelling-tests-"))
if (_REAL / "phonics").exists():
    (_TMP / "phonics").symlink_to(_REAL / "phonics")
os.environ["SPELLING_DATA_DIR"] = str(_TMP)
os.environ["SPELLING_STORE"] = "local"


@pytest.fixture(autouse=True)
def no_sign_in(monkeypatch):
    """Most tests call the API directly; test_auth.py turns sign-in back on."""
    monkeypatch.setenv("SPELLING_AUTH", "off")


@pytest.fixture(autouse=True, scope="session")
def real_data_untouched():
    db = _REAL / "db.json"
    before = db.stat().st_mtime_ns if db.exists() else None
    yield
    after = db.stat().st_mtime_ns if db.exists() else None
    assert before == after, "a test changed data/db.json"
