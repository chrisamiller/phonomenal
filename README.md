# Phonomenal

A spelling and phonics practice app.

Each day is a **mission**: spelling plus one or two extra activities she picks (writing,
sound splitting, sound match). Finished activities earn credits for decorating an
aquarium, with achievements along the way and a weekly goal of 5 practice days. After the
mission is done, games can be replayed for smaller bonus credits (capped per day).
Design notes: `docs/gamification.md`.

The spelling part is adaptive spaced-repetition practice. The child hears a word (and optionally a
sentence), types it, and gets instant feedback. After a correct answer they say how it felt
(Easy / A little hard / I guessed), which sets when the word comes back. Words they miss are
practised right away ("look, cover, write") and come back later in the same session.

## Run it locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --port 8811
```

Open http://127.0.0.1:8811 for practice. The grown-ups' page is http://127.0.0.1:8811/progress
(not linked from the practice page). It shows word progress, the credits economy, earned
achievements, and a writing export.

**Signing in:** every page needs a sign-in. The name is in `[auth]` in `settings.toml` (name
"Lexi"; the name isn't case-sensitive). The password comes from the `SPELLING_PASSWORD` environment
variable, so it never goes in the repo. Locally, start the server with
`SPELLING_PASSWORD=… .venv/bin/uvicorn app.main:app`, or use `SPELLING_AUTH=off` to skip sign-in. She stays signed in on a device for a
year, and the grown-ups' page has a Sign out link. The cookie is signed with a random key saved as
`data/secret_key`. `SPELLING_AUTH=off` turns sign-in off.

**Deploying:** `docs/deploy-gcp.md` covers Cloud Run, Cloud Storage and Firestore. The app and every
command-line tool use `data/db.json` by default, or Firestore with `SPELLING_STORE=firestore`.

**Backups:** the grown-ups' page has an **Export backup** link that downloads everything as one JSON
file (the same format as `data/db.json`). `restore-backup` loads one back into either store, after
saving the current data to `data/db.backup-before-restore-….json`.

To try it on a phone or Chromebook on the same Wi-Fi, run with `--host 0.0.0.0` and open
`http://<your-mac's-IP>:8811`.

**Android tip:** turn off keyboard suggestions/autocorrect for the child's keyboard
(Gboard → Settings → Text correction). The page asks the browser not to autocorrect, but
some keyboards still suggest words.

## Words and audio

Everything lives in `data/`: `data/db.json` (words, progress, review log) and `data/media/` (audio).

```bash
.venv/bin/python -m app.cli import-anki anki_data/*.apkg   # seed from Anki decks (already done)
.venv/bin/python -m app.cli add new_words.csv              # add words / sentences
.venv/bin/python -m app.cli export all_words.csv           # dump the word list
.venv/bin/python -m app.cli stats
.venv/bin/python -m app.cli import-prompts prompts.txt     # (re)load writing prompts
.venv/bin/python -m app.cli build-phonics                  # rebuild sound-splitting data
.venv/bin/python -m app.cli rank-words --show 100 [--csv ranks.csv]  # difficulty levels for new words
.venv/bin/python -m app.cli audio-queue                    # clips still needing good audio
.venv/bin/python -m app.cli export-backup [file.json]      # everything as one JSON file
.venv/bin/python -m app.cli restore-backup file.json       # replace everything with a backup (asks first)
.venv/bin/python -m app.cli generate-audio --engine google  # make them (see below)
.venv/bin/python -m app.cli prune-media [--delete]         # old clips no word uses
```

**Natural-sounding audio:** `docs/google-tts.md` explains how to set up Google Cloud, choose a
Chirp 3 HD voice (`tts-sample`), and generate every word and sentence clip. It's about
62k characters, which fits in the free tier.

## Tuning

These files are read on each request, so no restart is needed:

| File | What it controls |
|---|---|
| `settings.toml` | spelling scheduling, session size, mission rules, credit amounts, writing rules |
| `shop.toml` | aquarium items and prices |
| `achievements.toml` | achievements, their thresholds and their credits |
| `prompts.txt` | writing prompts; re-run `import-prompts` after editing |

Sound splitting and sound match use the CMU Pronouncing Dictionary (`data/phonics/cmudict.dict`, BSD licence).
Sound-match sounds are listed in `app/sounds.txt`. The clips live in `phonics_sounds/` on this Mac
and in the media bucket under `phonics_sounds/` (the app reads them from there on Cloud Run); they
aren't in git. `python -m app.cli build-sound-intros` makes the spoken introductions ("The sound is
/s/, as in sun") in `phonics_sounds/intros/`. It needs ffmpeg and Google TTS; re-run it after editing
`app/sounds.txt`, then upload the clips:
`gcloud storage rsync --recursive phonics_sounds gs://$BUCKET/phonics_sounds`.

CSV columns: `word,sentence,tags` (sentence and tags are optional; separate multiple tags with
`;`). Adding words or sentences never generates audio; missing clips join the audio queue
(`audio-queue`), and the browser's voice fills in until they exist. To change sentences:
`export`, edit the sentence column, then `add` the file back.

Capitalisation is kept: "May" (the month) and "may" are different words.

## How words are scheduled

- **Wrong answer** counts as "Again" (comes back the next day). The child can't mark a wrong answer as right.
- **Correct answer:** the button they pick maps to an FSRS rating (`[ratings]` in `settings.toml`).
- **Only the first try in a session counts.** Retries later in the session and cover-and-write practice are unscored.
- **Sessions mix difficulty** using `[session]` fractions:
  - easy words (low FSRS difficulty) for confidence;
  - medium words;
  - challenge words (high difficulty, missed last time, or brand new).
  
  A session starts and ends on an easy word. New words are limited per session and per day.
- **New words come easiest first** (`[ranking]` in `settings.toml`, `app/ranking.py`). `rank-words`
  gives every word a spelling-difficulty score:
  - how unexpected its letter patterns are, using letter-sound statistics from the whole list
  - syllables, suffix rules, length, and how common the word is
  - the grade of the list it came from

  Scores are split into 10 levels. Within a level, words that share a spelling pattern (all the
  "ai" words, say) come together.
  - Each session gets one of her own words (`priority_tags`), at most one irregular "heart" word,
    and a preview word from the next level once the current level is solid.
  - A homophone is never introduced within a week of its partner.
  - **Pacing:** when recent answers show she's struggling, new words slow down or pause until
    reviews recover.
  - The grown-ups' page shows her current level, the pace, and the next new words.
  - **Overrides:** export the words, put a number in the `level` column, then `add` the file back.
  - **Setup:** run `rank-words` once after setting up (and after changing the weights). It needs
    `requirements-tools.txt` for word frequencies. Words added later are ranked automatically.
    Set `mode = "tags"` to go back to `new_word_order`.
- **Mastery:** a word retires after `min_streak` correct answers in a row once its FSRS stability reaches `min_stability_days`. Mastered words come back as occasional spot checks; a miss puts the word back into rotation.

All of these settings are in `settings.toml`, and edits apply on the next session with no restart.

## Layout

```
app/main.py       web API + page serving
app/missions.py   daily mission + weekly goal
app/economy.py    credit ledger + economy report
app/achievements.py  achievement rules (all computed from stored data)
app/writing.py    prompts, daily prompt, responses, export
app/phonics.py    letter-to-sound alignment for sound splitting
app/ranking.py    word difficulty levels for introducing new words
app/aquarium.py   decorating projects (aquarium), shop, gallery
app/match.py      sound match: clip mapping, rounds, scoring
app/scheduler.py  FSRS wrapper, session mixing, mastery
app/grading.py    answer checking + letter highlighting
app/store.py      storage: LocalStore (data/db.json) or FirestoreStore; backups (dump/restore)
app/anki.py       .apkg reader
app/auth.py       sign-in (signed cookie)
app/tts.py        audio generation (macOS `say`)
app/tts_google.py audio generation (Google Chirp 3 HD)
app/cli.py        word-management commands
static/           the web app (plain HTML/CSS/JS modules in static/js, no build step)
```

## Tests

```bash
.venv/bin/python -m pytest -q
```
