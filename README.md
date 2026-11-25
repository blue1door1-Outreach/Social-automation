# Khuje Nao - daily Facebook storytelling automation

One original Bangla story every morning for the Khuje Nao Facebook Page: a
curiosity hook, a familiar Bangladeshi scene, a small problem, a slow reveal, a
warm ending and a question that invites comments. No prices, no stock, no selling.

The story is written, rendered, hosted and **scheduled in Buffer for 09:00
Asia/Dhaka** automatically. There is no approval step.

## How a day runs

```
01:30 UTC (07:30 Dhaka)   GitHub Actions starts
   -> pick today's topic (weekday + season + weather, never repeated in 45 days)
   -> Gemini writes the 7-step story, or a curated fallback story is used
   -> validate: Bangla only, 180-300 words, 8-18 paragraphs, title hook,
      closing question, no selling, no politics/religion/music/film/death
   -> fetch a people-free photo, or fall back to the text-only card
   -> commit the 1080x1350 image to docs/posts/
03:00 UTC (09:00 Dhaka)   Buffer publishes it to the Facebook Page
```

GitHub's schedule can start a few minutes late. Buffer holds the exact 09:00
slot, so a late start still lands on time.

## Stopping and tuning it

Everything is repository variables, no code changes:

| Variable | Default | What it does |
| --- | --- | --- |
| `AUTOMATION_ENABLED` | `true` | Set to `false` to pause the daily workflow completely |
| `STORY_LOCAL_TIME` | `09:00` | Buffer publish time in Asia/Dhaka (e.g. `08:00` or `10:00`) |
| `BUFFER_CHANNELS` | `facebook` | `facebook` only unless you add another connected channel |
| `GEMINI_MODEL` | `gemini-3.8-flash` | First model tried; `gemini-3.5-flash` and `gemini-flash-latest` are automatic fallbacks |

Set them in **Settings -> Secrets and variables -> Actions -> Variables**. To
stop posting, set `AUTOMATION_ENABLED` to `false`; nothing else is needed.

## What writes the story

| File | What it holds |
| --- | --- |
| `config/story_topics.json` | 28 story seeds across seasonal, family, nature, lifestyle, kindness, student, nostalgia and modest-dignity categories, four per weekday |
| `config/story_fallbacks.json` | 7 fully written stories, used when the model is busy or returns something that fails the rules |
| `state/story_history.json` | Topics already used, so the rotation never repeats within 45 days |
| `config/brand.json` | Palette, tone, caption limits, hashtag pools, banned phrases, story filters |
| `config/context.json` | Location, season windows, trend filters, photo queries and concepts |

The topic chooser weights the weekday category first, then season and weather. A
Thursday is a school, college, university or friendship story; a Wednesday is
kindness; a Sunday is family; a Friday is nostalgia or quiet dignity. The model
receives the chosen seed (character, desire, obstacle, emotion, reveal, ending)
and writes a fresh story every time, so the same seed does not read the same twice.

## Safety rules in the engine

A story is published only when every check passes:

- Bangla only, 180-300 Bangla words, 8-18 short paragraphs.
- A hook title, a gradual reveal, and a closing question.
- No price, discount, stock, delivery or "buy now"; no preachy moral.
- No politics, religion, music, film, celebrity, violence, death, disaster or disease.
- No English letters in the story fields.
- Photos must be relevant, clean and contain no people at all; otherwise the
  graphic is text-only.
- One post per day. The ledger and history in `state/` are committed by the
  workflow, so a rerun cannot double-post.

If Gemini is overloaded, the engine tries the next model, then a curated
fallback. A day is never left empty because of an API spike.

## Running it by hand

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest

# a fresh story for today, no publishing
python -m src.main --mode preview --story

# a fresh story from a specific topic
python -m src.main --mode preview --story --date 2026-11-30

# publish the reviewed day to Facebook immediately
python -m src.main --mode queue --date 2026-11-30 `
  --image-url https://raw.githubusercontent.com/<owner>/<repo>/main/docs/posts/<post_id>.png `
  --due-local 09:00
```

Artifacts land in `out/<date>/`: `image.png`, `caption.txt`, `post.json`,
`report.md`. `--now` publishes immediately instead of scheduling.

Useful scripts:

```powershell
python scripts/check_buffer.py     # list the Buffer organization and channels
python scripts/preview_week.py --days 7
```

## GitHub setup (already done)

Secrets:

| Secret | Value |
| --- | --- |
| `GEMINI_API_KEY` | Google AI Studio key |
| `BUFFER_API_KEY` | Buffer API key |

Variables:

| Variable | Value |
| --- | --- |
| `BUFFER_ORGANIZATION_ID` | Buffer organization id |
| `BUFFER_CHANNEL_FB` | Facebook channel id |
| `BUFFER_CHANNELS` | `facebook` |
| `ENABLE_QUEUEING` | `true` |
| `AUTOMATION_ENABLED` | `true` |
| `STORY_LOCAL_TIME` | `09:00` |
| `PUBLIC_IMAGE_BASE_URL` | raw host for the reviewed image |

The workflow needs **Settings -> Actions -> General -> Workflow permissions ->
Read and write permissions** so it can commit the image and state.

## Buffer

- Endpoint `https://api.buffer.com`, header `Authorization: Bearer <API key>`.
- API key page: `https://publish.buffer.com/settings/api`.
- Each post uses `customScheduled` with `dueAt` = `STORY_LOCAL_TIME` in
  `Asia/Dhaka`, and Facebook post metadata (`type: post`).
- Buffer fetches the image at publish time, so the raw GitHub URL must stay
  public and unchanged.

## Layout

```
.github/workflows/daily-post.yml   story -> image -> Buffer (no approval)
config/story_topics.json           28 topic seeds
config/story_fallbacks.json        7 curated stories
config/brand.json                  brand, palette, hashtag pools, filters
config/content.json                short-note library (non-story fallback)
config/context.json                season, trend filters, photo queries
src/story_engine.py                topic rotation, model chain, validation
src/writer.py                      story formatting, hashtags, Gemini for notes
src/main.py                        pipeline, gates, scheduling, exit codes
src/graphics.py                    headless-Chrome renderer
src/validate*.py                   caption, image and URL checks
src/buffer_client.py               Buffer GraphQL client
state/ledger.jsonl                 publish history
state/story_history.json           used story topics
docs/posts/                        public story images
out/                               generated artifacts (gitignored)
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| No post today | Check `AUTOMATION_ENABLED` is `true` and the workflow run in the Actions tab |
| `Gemini unavailable` in the log | Expected sometimes; the run used a curated fallback and still posted |
| `channel id ... not found` | Re-run `python scripts/check_buffer.py` and update `BUFFER_CHANNEL_FB` |
| Post scheduled for the wrong time | Change `STORY_LOCAL_TIME` (Asia/Dhaka, 24h `HH:MM`) |
| Story feels repetitive | Add more seeds to `config/story_topics.json`; the chooser avoids the last 45 days |
| Text-only card | No clean people-free photo passed; adjust the concept queries in `config/context.json` or accept it |
| Workflow red on a duplicate day | The queue step treats an already-posted day as success; a real error is shown in `report.md` |
