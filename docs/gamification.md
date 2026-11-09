# Daily missions & gamification: design decisions

Status: all built: mission, weekly goal, day streaks, credits, achievements, writing,
sound splitting, sound match, aquarium.

## Daily mission
- A day = spelling + 1–2 other activities; the child chooses which.
- **Spelling:** a fixed 15 words (no timer). Tune `session.size` as needed.
- **Weekly goal:** 5 mission days per week, Monday to Sunday. Missing it costs nothing.
- **Rematch cards:** words missed before come back as "Rematch!", with a credit bonus.
- If nothing is due and today's new words are used up, the session fills with extra new words (`top_up_with_new`).

## Writing
- One random approved prompt per day, never repeated within 30 days. Prompts come from `prompts.txt`.
- Spellcheck and autocorrect off. No read-aloud of the prompt, no "read mine back."
- Gentle sentence counter (goal: 3–4 sentences), no grading.
- Store: prompt, text, start/finish time.
- Export: a plain dump of all responses for offline analysis.

## Sound splitting (segmentation)
- Two questions per word: "How many sounds?" then tap the gaps to split it.
- Conventions:
  - Digraphs, vowel teams, r-controlled vowels and double letters are one tile/sound: sh|i|p, r|ai|n, c|ar, b|a|ll.
  - Blends are separate: s|t|o|p.
  - Silent letters join their partner: kn|ee, l|a|mb.
  - **x, qu and nk = one tile and one sound** (b|o|x = 3, th|i|nk = 3, as UFLI teaches nk).
  - **Silent-e words are excluded.**
  - Multi-syllable words come later.
- Data: CMU Pronouncing Dictionary sounds plus a rule-based letter-to-sound aligner. Only clean or reviewed words are used.

## Sound match (decoding)
- A sound plays; she taps every word that contains it.
- Distractors use the same spelling for a different sound (snow vs cow), plus near-miss sounds.
- Feedback highlights the spelling of the sound in each word.
- Tracks accuracy per sound-spelling pattern and favours weak ones.
- 6 rounds of 8 word cards.
- Each round opens with a spoken introduction: "The sound is /s/, as in sun." 🔊 replays just the
  sound; 💡 Hint replays the introduction and shows the example word. The example word is never
  one of the cards on screen.
  - Clips are in `phonics_sounds/intros/`, built by `build-sound-intros` (`app/sound_intros.py`).
  - Each joins the Google voice saying "The sound is", the recorded sound clip, then the voice
    saying "as in <word>", all at the same volume.
  - There's one clip per example word in `sounds.txt`. Re-run after editing that file.
- Clips: `phonics_sounds/` (46 mp3s, not in git; on Cloud Run they come from the media bucket), listed in `app/sounds.txt`. Which clip a word's sound uses depends on
  its spelling, following the manifest: "dog" uses the short-o clip, "saw" the or/aw clip.
- 42 of 45 sounds have enough one-syllable words. Schwa, ure and zh are skipped.
- Words with two pronunciations (bow, read, live, wind…) are left out.
- A word is left out of a round when another sound in it overlaps the target, e.g. *box* in a /k/ round.

## Credits economy
- Earned for effort, never for accuracy or button choices. Each activity pays in full once per day;
  replays (games only, not writing) pay a bonus until a daily cap. Starting values:

  | Source | Credits |
  |---|---|
  | Activity done | 10 |
  | Replay after the first time (spelling, splitting, match) | 5, up to 50 a day |
  | Mission done | 20 |
  | Weekly goal | 50 |
  | Rematch won | 5 |
  | Word mastered | 5 |
  | Achievement | varies |

- **Ledger, append-only:** every credit change is one row: `{ts, practice_day, iso_week, amount (+/-), source, detail}`.
  The balance is computed from the ledger; nothing is stored separately.
- **Economy report on the progress page:**
  - credits earned and spent per week, with balance over time
  - average earned per practice day, by source
  - purchases (item, price, date), and days spent saving before each purchase
  - "weeks to afford" the most expensive unowned item at the current earning rate
- All amounts and prices live in config so they can be tuned without code changes.

## Aquarium (first decorating project)
- **Fish:** guppy 20, neon tetra 20, goldfish 30, clownfish 40, blue tang 50, angelfish 50, pufferfish 60, seahorse 70, jellyfish 90, sea turtle 120, octopus 120, whale shark 300.
- **Coral and plants:** seaweed 15, brain coral 30, fan coral 35, staghorn 40, anemone 45, kelp forest 60.
- **Decorations:** pebbles 10, starfish 25, bubbler 40, treasure chest 50, diver 60, glowing crystals 80, castle 120, sunken ship 150.
- **Tank:** bigger tank 200, sand colour 30, backgrounds 50 each.
- Art: hand-drawn SVG in `static/js/art.js`, all in one style: dark outline, toon shading from a
  shared gradient, a highlight, and big eyes. Tails, fins, tentacles, lids and flags are separate
  parts that CSS animates.
- Scene: deep-water gradient, swaying light rays, a rippling surface, drifting specks, distant
  rocks, and a seabed with dunes, pebbles and shells. Decorations and fish cast soft shadows.
- Motion (`static/js/aquarium.js`): fish steer toward targets, turn smoothly and tilt as they climb.
  Some swim nearer the glass and some farther back, passing in front of or behind decorations.
- Personalities: guppies and tetras school; clownfish stay by an anemone; seahorses drift between
  plants; the turtle glides and comes up for air; the whale shark cruises mid-water; jellyfish
  pulse upward and sink; the octopus hides behind decorations.
- Interactions: tap the water to drop food (fish chase and eat it, and get full after 3 flakes).
  Tap a fish and it darts away; the pufferfish puffs up, the octopus squirts ink, the jellyfish
  flashes, and the turtle and seahorse show a heart. Tapping a decoration makes it bounce.
- Day and night: night-time follows the clock (7pm–7am) and has a toggle. At night, plankton and
  crystals glow and the fish slow down.
- New purchases make an entrance: fish splash in and swim a lap while the others come to look;
  decorations sink to the sand with a puff.
- Items are drag-placed with "Move things". Reduced-motion settings show a still tank.
- Projects can be archived to a gallery and a new one started; credits carry over.


## Achievements
See `achievements.toml`. Day-streak achievements (3, 5, 7, 14 and 30 days in a row) are `repeatable`:
every new streak that reaches the length earns them again. Never lost or reset.
- **During a game:** credit pop-ups appear as they happen. Achievements are saved for the game's
  completion page, which lists the credits earned and every new achievement.
- **Trophy shelf:** shows only earned achievements, newest first, with a "New today!" badge.
  It also shows a count of how many are still to discover; unearned ones aren't listed.
- **Sound match only counts real tries:** a round counts toward the trick-word and streak
  achievements only if at least one right word was tapped. Checking an empty round
  isn't rewarded.
- Changing an achievement's thresholds later hides any stored awards that no longer match.
