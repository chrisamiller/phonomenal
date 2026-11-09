"""Text-to-speech for words/sentences that don't already have recorded audio.

This uses macOS `say`; app/tts_google.py is the higher-quality Google engine
(docs/google-tts.md). The rest of the app only cares that it gets audio bytes back.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

DEFAULT_VOICE = "Samantha"


def available() -> bool:
    return bool(shutil.which("say") and shutil.which("afconvert"))


def synthesize(text: str, voice: str = DEFAULT_VOICE, rate: int = 160) -> bytes:
    """Return AAC (.m4a) audio for `text`. `rate` is words per minute; kept a little slow."""
    with tempfile.TemporaryDirectory() as d:
        aiff, m4a = Path(d) / "out.aiff", Path(d) / "out.m4a"
        subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff), text], check=True)
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(aiff), str(m4a)], check=True)
        return m4a.read_bytes()
