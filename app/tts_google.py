"""Google Cloud Text-to-Speech (Chirp 3 HD voices). Setup and costs: docs/google-tts.md.

Needs `pip install -r requirements-tts.txt` and Application Default Credentials
(`gcloud auth application-default login`). Imported only when the google engine is used.
"""
import random
import time

DEFAULT_VOICE = "en-US-Chirp3-HD-Leda"
SOURCE = "google-chirp3"

_client = None


def _tts():
    try:
        from google.cloud import texttospeech
    except ImportError:
        raise SystemExit("google-cloud-texttospeech is not installed: .venv/bin/pip install -r requirements-tts.txt")
    return texttospeech


def client():
    global _client
    if _client is None:
        _client = _tts().TextToSpeechClient()   # thread-safe; shared by the worker threads
    return _client


def synthesize(text: str, voice: str = DEFAULT_VOICE, rate: float = 0.9, attempts: int = 6) -> bytes:
    """Return MP3 audio for `text`, retrying with backoff on quota and transient errors."""
    from google.api_core import exceptions as gx
    t = _tts()
    request = dict(
        input=t.SynthesisInput(text=text),
        voice=t.VoiceSelectionParams(language_code="-".join(voice.split("-")[:2]), name=voice),
        audio_config=t.AudioConfig(audio_encoding=t.AudioEncoding.MP3, speaking_rate=rate),
    )
    retry = (gx.ResourceExhausted, gx.ServiceUnavailable, gx.DeadlineExceeded, gx.InternalServerError)
    for attempt in range(attempts):
        try:
            return client().synthesize_speech(**request).audio_content
        except retry:
            if attempt == attempts - 1:
                raise
            time.sleep(min(60, 2 ** attempt) + random.random())


def voices(language: str = "en-US") -> list[str]:
    """Names of the Chirp 3 HD voices available for a language."""
    return sorted(v.name for v in client().list_voices(language_code=language).voices if "Chirp3-HD" in v.name)
