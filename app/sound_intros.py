"""Spoken introductions for sound match: "The sound is /s/, as in sun."

Each clip joins three pieces: a Google voice saying "The sound is", the recorded sound clip
from phonics_sounds/, and the voice saying "as in <example>". The recorded sound is used
rather than asking the voice to say "ssss", which text-to-speech does badly.
One clip per (sound, example word) from app/sounds.txt, plus one with no example.
Built by `python -m app.cli build-sound-intros` (needs ffmpeg and Google TTS set up).
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import match

INTRO_DIR = match.CLIPS_DIR / "intros"
PEAK_DB = -3.0          # every piece is scaled to this peak so the voice and the sound match
GAPS = (0.2, 0.3)       # seconds of silence before and after the sound


def name(sound: str, example: str | None) -> str:
    return f"{sound}__{example}.mp3" if example else f"{sound}.mp3"


def path_for(sound: str, example: str | None) -> Path | None:
    """The intro clip for a round, falling back to the one without an example."""
    for p in (INTRO_DIR / name(sound, example), INTRO_DIR / name(sound, None)):
        if p.exists():
            return p
    return None


def _peak(path: Path) -> float:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.search(r"max_volume: (-?[\d.]+) dB", out)
    return float(m.group(1)) if m else 0.0


def _join(pieces: list[Path], out: Path) -> None:
    """Concatenate clips with short gaps, each peak-normalised, as 44.1 kHz mono mp3."""
    args, chains, labels = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"], [], []
    for i, p in enumerate(pieces):
        args += ["-i", str(p)]
        gain = PEAK_DB - _peak(p)
        chains.append(f"[{i}]aresample=44100,aformat=channel_layouts=mono,volume={gain:.1f}dB[p{i}]")
    for i, secs in enumerate(GAPS[: len(pieces) - 1]):
        chains.append(f"anullsrc=r=44100:cl=mono,atrim=duration={secs}[g{i}]")
    for i in range(len(pieces)):
        labels.append(f"[p{i}]")
        if i < len(pieces) - 1:
            labels.append(f"[g{i}]")
    graph = ";".join(chains) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]"
    subprocess.run(args + ["-filter_complex", graph, "-map", "[out]", "-codec:a", "libmp3lame", "-q:a", "4", str(out)],
                   check=True)


def build(voice: str, rate: float, only: list[str] | None = None) -> int:
    """Make every intro clip. Returns how many were written."""
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is needed: brew install ffmpeg")
    from . import tts_google
    INTRO_DIR.mkdir(exist_ok=True)
    sounds = {k: v for k, v in match.manifest().items() if not only or k in only}
    made = 0
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        lead = tmp / "lead.mp3"
        lead.write_bytes(tts_google.synthesize("The sound is", voice, rate))
        for sid, s in sounds.items():
            clip = match.CLIPS_DIR / s["file"]
            _join([lead, clip], INTRO_DIR / name(sid, None))
            made += 1
            for ex in dict.fromkeys(s["examples"]):
                tail = tmp / f"as-in-{ex}.mp3"
                tail.write_bytes(tts_google.synthesize(f"as in, {ex}.", voice, rate))
                _join([lead, clip, tail], INTRO_DIR / name(sid, ex))
                made += 1
            print(f"  {sid}: {', '.join(dict.fromkeys(s['examples']))}")
    return made
