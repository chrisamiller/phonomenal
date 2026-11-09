"""Read words and audio out of Anki .apkg files (modern zstd-compressed format and legacy)."""
import html
import io
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import zstandard

SOUND_RE = re.compile(r"\[sound:([^\]]+)\]")
TAG_RE = re.compile(r"<[^>]+>")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _varint(b: bytes, i: int) -> tuple[int, int]:
    r = shift = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << shift
        shift += 7
        if not x & 0x80:
            return r, i


def _media_names_protobuf(buf: bytes) -> list[str]:
    """Decode Anki's MediaEntries protobuf: repeated {1: name, 2: size, 3: sha1}."""
    names, i = [], 0
    while i < len(buf):
        _, i = _varint(buf, i)
        ln, i = _varint(buf, i)
        sub, i = buf[i:i + ln], i + ln
        j, name = 0, ""
        while j < len(sub):
            key, j = _varint(sub, j)
            if key & 7 == 2:
                l, j = _varint(sub, j)
                if key >> 3 == 1:
                    name = sub[j:j + l].decode()
                j += l
            else:
                _, j = _varint(sub, j)
        names.append(name)
    return names


def _clean(field: str) -> str:
    text = SOUND_RE.sub("", field)
    return html.unescape(TAG_RE.sub("", text)).replace("\xa0", " ").strip()


def read_apkg(path: Path) -> tuple[str, list[dict], dict[str, bytes]]:
    """Return (deck_name, [{word, audio}], {media_name: bytes})."""
    dctx = zstandard.ZstdDecompressor()
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        modern = "collection.anki21b" in names
        if modern:
            col = dctx.decompress(z.read("collection.anki21b"), max_output_size=1 << 30)
            media_names = _media_names_protobuf(dctx.decompress(z.read("media"), max_output_size=1 << 30))
            media_index = {name: str(i) for i, name in enumerate(media_names)}
        else:
            col = z.read("collection.anki21" if "collection.anki21" in names else "collection.anki2")
            media_index = {v: k for k, v in json.loads(z.read("media")).items()}

        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
            tmp.write(col)
            tmp.flush()
            db = sqlite3.connect(tmp.name)
            db.create_collation("unicase", lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower()))
            decks = [r[0] for r in db.execute("select name from decks where name != 'Default'")] if modern else []
            fields = {}
            if modern:
                for ntid, ord_, name in db.execute("select ntid, ord, name from fields"):
                    fields.setdefault(ntid, {})[name] = ord_
            notes = db.execute("select mid, flds from notes order by id").fetchall()
            db.close()

        entries, media = [], {}
        for mid, flds in notes:
            parts = flds.split("\x1f")
            audio = next((m.group(1) for p in parts for m in [SOUND_RE.search(p)] if m), None)
            fmap = fields.get(mid, {})
            # "Spelling TTS" decks use a Word field; "Basic (type in the answer)" decks put the word on the Back.
            idx = fmap.get("Word", fmap.get("Back"))
            word = _clean(parts[idx]) if idx is not None else next((c for c in map(_clean, parts) if c), "")
            if not word:
                continue
            entries.append({"word": word, "audio": audio})
            if audio and audio in media_index and audio not in media:
                raw = z.read(media_index[audio])
                media[audio] = dctx.decompress(raw, max_output_size=1 << 28) if modern else raw

    deck = decks[0] if decks else path.stem
    return deck, entries, media
