# Google Chirp 3 HD voices

The app plays a recorded clip for each word and sentence when one exists. Today about 1,180
words have Anki recordings, 788 words use macOS `say` (robotic), and no sentences have audio.
That means the browser's own voice reads every sentence. These steps generate natural-sounding
clips with Google Cloud Text-to-Speech's **Chirp 3 HD** voices.

**Cost:** about 62,000 characters (2,768 clips), or about 69,000 (3,960 clips) if you also
re-voice the Anki words. Chirp 3 HD includes 1 million free characters a month, so this
should cost nothing. After the free tier it's $30 per million characters, so even a full re-run
costs about $2. Google does require a billing account linked to the project.

## 1. One-time Google Cloud setup

```bash
brew install --cask google-cloud-sdk          # or the installer from cloud.google.com/sdk
gcloud auth login                             # opens a browser

# Make a project (the ID must be globally unique) and select it
gcloud projects create spelling-tts-cm --name="Spelling TTS"
gcloud config set project spelling-tts-cm

# Link billing (required even within the free tier)
gcloud billing accounts list                  # copy the ACCOUNT_ID
gcloud billing projects link spelling-tts-cm --billing-account=XXXXXX-XXXXXX-XXXXXX

gcloud services enable texttospeech.googleapis.com

# Credentials for the Python client ("Application Default Credentials")
gcloud auth application-default login
gcloud auth application-default set-quota-project spelling-tts-cm
```

Optional: set a budget alert (for example $5) under **Billing → Budgets & alerts** in the
Cloud console. You'll get an email if something unexpected happens.

## 2. Install the client

```bash
.venv/bin/pip install -r requirements-tts.txt
```

## 3. Pick a voice

```bash
.venv/bin/python -m app.cli tts-sample --play
```

This writes `tts_samples/<Voice>.mp3` for six voices (Leda, Kore, Aoede, Achernar, Charon and
Puck), each saying a word and a sentence. With `--play` they play one after another. Try other
voices and texts like this:

```bash
.venv/bin/python -m app.cli tts-sample --voices Despina,Callirrhoe,Iapetus \
    --text "through" --text "We walked through the forest to the lake." --rate 0.85 --play
```

To list every Chirp 3 HD voice:

```bash
.venv/bin/python -c "from app import tts_google; print(*tts_google.voices(), sep='\n')"
```

`--rate` is the speaking speed: 1.0 is normal and the default is 0.9. Something between 0.85
and 0.9 is usually clearest for spelling. It's worth letting her choose the voice.

## 4. Generate a small batch and listen

```bash
cp data/db.json data/db.backup-before-chirp.json
.venv/bin/python -m app.cli generate-audio --engine google --voice en-US-Chirp3-HD-Leda --limit 20 --rate 0.85
```

Clips are saved as `data/media/<id>.chirp.mp3` and `<id>.sentence.chirp.mp3`, with source
`google-chirp3`. The app uses them immediately and needs no restart. Practise a few words to
check them.

## 5. The full run

```bash
# Replace the macOS clips and add every sentence (2,768 clips)
.venv/bin/python -m app.cli generate-audio --engine google --voice en-US-Chirp3-HD-Leda

# Or also re-voice the Anki recordings, so every word uses the same voice (3,960 clips)
.venv/bin/python -m app.cli generate-audio --engine google --voice en-US-Chirp3-HD-Leda --replace anki --rate 0.85
```

- It sends 4 requests at a time (`--workers`) and saves progress every 25 clips. Ctrl-C is safe;
  running it again picks up where it stopped.
- Rate-limit and temporary errors are retried with backoff. Clips that still fail are reported
  and stay in the queue, so run the command again to retry them.
- `audio-queue` shows what's left.

Afterwards, delete the old clips that no word uses any more:

```bash
.venv/bin/python -m app.cli prune-media            # shows what would be removed
.venv/bin/python -m app.cli prune-media --delete
```

**Switching voices later:** add `--replace google-chirp3 --voice <new voice>`. The file names
stay the same, so hard-refresh the browser to avoid hearing cached clips.

## Things to check by ear

- **Single words with two pronunciations:** read, lead, live, wind, tear and similar. On its own,
  the word could come out either way. The sentence clip will be right, because the context
  decides the pronunciation.
- **Very short words** (a, I, ah, oh) can sound clipped. If one does, re-record it with
  `say` or another voice. You can also add a better clip by hand: put the file in `data/media/`
  and set the word's `audio` field.

## Troubleshooting

| Message | Fix |
|---|---|
| `DefaultCredentialsError` | Run `gcloud auth application-default login`. |
| `SERVICE_DISABLED` / `403 ... has not been used in project` | Run `gcloud services enable texttospeech.googleapis.com`, then wait a minute. |
| Warning about a missing quota project | Run `gcloud auth application-default set-quota-project <project>`. |
| `BILLING_DISABLED` | Link a billing account (step 1). |
| `ResourceExhausted` / many retries | Use fewer workers, e.g. `--workers 2`. |
| `400 ... voice ... does not exist` | Check the name with the voice list command. The format is `en-US-Chirp3-HD-<Name>`. |
| `google-cloud-texttospeech is not installed` | Run `.venv/bin/pip install -r requirements-tts.txt`. |
