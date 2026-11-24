# Khuje Nao - daily Facebook/Instagram automation

A cautious pipeline that produces one engagement-first winter post per day for a
shop in Dhaka, in Bangla: a curated style, care or layering idea, a short Bangla
caption, a branded 1080x1350 editorial graphic with a real photo (no people in
it), validation, then an optional Buffer queue.

**Current state: preview works with no credentials.** Publishing stays blocked
until the brand config is verified and Buffer access is configured.

## Requirements

- Python 3.11+ and the packages in `requirements-dev.txt`.
- **Headless Chrome or Edge.** Pillow on this machine cannot shape Bengali (no
  HarfBuzz), so the Bangla graphic is drawn as HTML and screenshotted by Chrome.
  Chrome is auto-detected; set `CHROME_PATH` to override. GitHub's `ubuntu-latest`
  runner already ships Chrome.

## Test it locally (5 minutes, no keys)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

python -m pytest
python -m src.main --offline
```

Open:

- `out/<today>/image.png` - the graphic
- `out/<today>/caption.txt` - caption plus hashtags
- `out/<today>/report.md` - what happened and why
- `out/<today>/post.json` - the machine-readable post

`--offline` uses the deterministic template writer and never calls Gemini.
Nothing is queued.

Several days at once:

```powershell
python scripts/preview_week.py --days 7
python scripts/preview_week.py --days 7 --start 2026-11-23
python scripts/preview_week.py --days 7 --online   # try Gemini instead of templates
```

Offline is the default there so output is repeatable. Each day is a normal
preview run.

Two review helpers:

```powershell
python scripts/check_ideas.py     # render + validate all 36 ideas, out/ideas/sheet.png
python scripts/check_photos.py    # contact sheet of the photo set, out/photos_sheet.png
```

## What it does

```
content library (config/content.json)
   -> one idea for the day (deterministic rotation, 36 ideas)
   -> caption (Gemini, or deterministic templates), in Bangla
   -> photo (assets/photos, tag-matched, always people-free)
   -> graphic (headless Chrome HTML, 1080x1350, editorial)
   -> validation (caption rules, image decode, size, dimensions)
   -> [gate] duplicate check, public image bytes, Buffer channels
   -> queue per platform, or stop
   -> report.md + post.json + artifacts
```

Two separate modes:

| Mode | What happens | Exit code |
| --- | --- | --- |
| `preview` | Generates `image.png`, `caption.txt`, `post.json`, `report.md`. Publishes nothing. | 0 ready, 1 blocked |
| `queue` | Reuses the exact reviewed files for that date, re-validates them, checks the public image bytes, then queues Facebook and Instagram separately. | 0 queued, 1 blocked/partial/unknown |

A non-zero exit is intentional: a skipped post should be visible, not silent.

## Files the pipeline reads

| File | What goes in it |
| --- | --- |
| `config/brand.json` | Name, palette, tone, CTA (English and Bangla), caption limits, hashtag pools, banned phrases, timezone (`Asia/Dhaka`), `verified` |
| `config/content.json` | The idea library: 36 style, care, kids and Dhaka notes, each with a title, body, short takeaway, Bangla copy, audience and tags |
| `config/products.json` | Optional reference catalogue, kept for future product posts. The daily tips do not read it |
| `config/research.json` | Legacy research settings, kept for experiments. Not used by the daily flow |
| `assets/photos/credits.json` | The photo set and its licences. Every image is people-free |
| `assets/fonts/` | Noto Serif/Sans Bengali, embedded into the graphic as base64 |

The writer may only use the selected idea and the brand config. It never sells
and never states a price, discount, stock level, delivery promise, material or
availability.

### Content library

`config/content.json` is the source of every post. Each idea has:

- `title` - the big graphic headline (max 60 characters)
- `body` - the useful part, used in the caption
- `note` - a short takeaway under the headline (max 90)
- `title_bn`, `body_bn`, `note_bn` - the Bangla copy that actually ships. All
  three are required together; the English fields stay as the source of truth for
  reviewers and as a fallback
- `audience` - `kids`, `men`, `women` (picks hashtag groups)
- `tags` - `layering`, `care`, `dhaka`, `style`, `winter`, `kids`
- `type` - `STYLE TIP`, `LAYERING`, `CARE`, `CHECKLIST`, `KIDS`, `DHAKA NOTE`, `COLOUR`

Ideas rotate by date, so the same day always gets the same idea and 36 days pass
before a repeat. Add or edit ideas freely; the loader rejects duplicate ids,
titles over 60 characters and notes over 90.

### Photos

`assets/photos/` holds a small curated set of Creative Commons (CC0) and public
domain stock photos, each recorded with its licence and source in
`credits.json`. Two rules are absolute:

- **No people, at all.** No faces, and therefore never a photo of a woman. A
  shortlist is reviewed by eye before it is added.
- **Relevant or nothing.** The post picks the best tag match for the idea; if no
  photo matches, the graphic falls back to the text-only layout.

Rarer tags weigh more than common ones, so a `kids` idea prefers a knit hat over
a generic winter scene. Ties rotate by date. To refresh the set, edit
`scripts/fetch_photos.py` and run it; to review the current set, run
`python scripts/check_photos.py`.

### Product catalogue (optional)

`config/products.json` still holds the 21 items, with `price: null` and
`stock: "unknown"`. It is not used by the daily tip posts and no product name is
mentioned. It is there if you later want separate product posts.

### Order of operations

1. Preview locally with no credentials (now).
2. Edit the ideas in `config/content.json` and their Bangla copy, the palette and
   the CTA until you like the output.
3. Set `verified: true` in `brand.json`.
4. Create the Buffer account, connect Facebook and Instagram, and add the API
   key. This is the point where Buffer details become necessary.
5. Run `python scripts/check_buffer.py`, then a single supervised queue post.
6. Only then add `ENABLE_QUEUEING=true`.

### Captions, hashtags, graphics

- Engagement-first: a style, layering, care or Dhaka note. No product pushes, no
  prices, no stock, no "buy now".
- 80-320 characters, in Bangla, 5-10 hashtags. The caption ends with the Bangla
  CTA (`পরে পড়ার জন্য সেভ করুন`) and a short follow line. Banned phrases include
  the Bangla selling words (`কিনুন`, `ডিসকাউন্ট`, `স্টক`, ...).
- One required tag (`#KhujeNao`) plus audience tags, winter tags and Dhaka tags.
  Pools live in `config/brand.json`; the offline writer fills roughly
  1 + 2 audience + 4 winter + 2 local, then adds filler up to the limit.
  Hashtags stay ASCII (letters, digits, underscore) so every platform accepts
  them; only the caption and the graphic are Bangla.
- Instagram's limit is **2,196 UTF-16 code units**, and a line break counts as
  2. The validator measures the real payload, not `len()`.
- The graphic uses your palette: Warm White `#FFFBF9` paper, Sand Beige
  `#E3CAA5`, Taupe `#ADB7B3` and Deep Brown `#594E38` for text. A photo band on
  top, a serif Bangla headline, a type pill, a palette signature, the brand, the
  CTA and the follow line.
- The graphic is rendered as HTML by headless Chrome so Bengali shapes and joins
  correctly; both Bengali fonts are embedded as base64, so no font is needed at
  screenshot time. A plain-ASCII, photo-free run falls back to the Pillow layout
  so previews still work on a machine without Chrome.
- No models: the photo never contains a person. Headlines are measured and
  shrunk; if the text cannot fit, rendering fails instead of cropping.

## Safety gates (queue mode)

All of these must pass, or nothing is published:

1. `ENABLE_QUEUEING=true`
2. `brand.json` is verified
3. `BUFFER_API_KEY` and `BUFFER_ORGANIZATION_ID` are set
4. Both channel ids are set (`BUFFER_CHANNEL_FB`, `BUFFER_CHANNEL_IG`)
5. Buffer returns those channels in that organization, with matching services
6. A public HTTPS URL serves exactly the bytes of the reviewed image (SHA-256 match, with retries)
7. No queued or unknown post already exists for that date

Duplicate handling:

- Both platforms queued -> skip.
- Facebook queued, Instagram failed -> resume only Instagram.
- Timeout or 5xx -> recorded as `unknown`, never retried automatically. Check Buffer first.
- Any queued post for that date blocks a second post, even with different content.

The ledger is `state/ledger.jsonl`, one JSON object per line, committed by the
workflow. It is the only reason a rerun cannot double-post.

## Buffer setup

The client uses Buffer's current GraphQL API. This was checked against
`https://developers.buffer.com` on 2026-11-23:

- endpoint `https://api.buffer.com`
- auth header `Authorization: Bearer <API key>`
- API key page `https://publish.buffer.com/settings/api`

Steps:

1. Create a Buffer account and connect the Facebook Page and the Instagram
   professional account you want to post to.
2. Open `https://publish.buffer.com/settings/api` and create an API key. The
   page shows whether your plan includes API access.
3. Copy the template and fill in the key:

   ```powershell
   Copy-Item .env.example .env
   ```

   ```dotenv
   BUFFER_API_KEY=your-key-here
   ```

   `.env` is gitignored. Real environment variables always win over the file.
4. List your organization and channels without creating anything:

   ```powershell
   python scripts/check_buffer.py
   ```

5. Put the ids into `.env`:

   ```dotenv
   BUFFER_ORGANIZATION_ID=...
   BUFFER_CHANNEL_FB=...
   BUFFER_CHANNEL_IG=...
   ```

6. Host the reviewed image on a public HTTPS URL. The repository workflow does
   this automatically on GitHub Pages (see "Hosting the image" below). For a
   manual run, upload `out/<date>/image.png` anywhere public and pass the URL.
7. Keep `ENABLE_QUEUEING` empty for now. Run a preview, inspect it, host the
   image, then publish:

   ```powershell
   python -m src.main --mode preview --date 2026-11-23
   python -m src.main --mode queue --date 2026-11-23 `
     --image-url https://example.github.io/repo/posts/2026-11-23-abc123.png
   ```

`queue` never regenerates content: it loads `post.json`, verifies the PNG hash,
and refuses if the file changed.

By default Buffer inserts the post into the next free queue slot
(`mode: addToQueue`). Give each channel a 10:00 slot in Buffer's own posting
schedule if you want a predictable time.

For a one-off post at an exact time, set `BUFFER_DUE_AT` in `.env` to an
ISO-8601 UTC timestamp, e.g. `2026-11-24T04:00:00Z` (10:00 Asia/Dhaka). The
client then switches to `customScheduled`. Do not set it as a repository
variable: a single fixed timestamp would target every post at the same moment.

**Media rule:** Buffer fetches the image when the post publishes, not when it is
created. The URL must stay public, direct, HTTPS and unchanged. Editing or
recompressing the file after queueing breaks the hash guarantee and can publish
the wrong image.

## GitHub Actions

`.github/workflows/daily-post.yml` runs at **04:00 UTC = 10:00 Asia/Dhaka**
(UTC+6, no daylight saving).

- Scheduled runs and `mode=preview` dispatches only generate a preview and
  upload `out/` as an artifact. Nothing is published.
- A `mode=queue` dispatch runs the preview job first, then a `publish` job that
  waits for the **`github-pages` environment** approval, downloads that same
  artifact, commits the reviewed image to `docs/posts/`, deploys GitHub Pages,
  queues to Buffer, and commits the ledger.

Because `deploy-pages` waits for the deployment to finish, the image is live
before Buffer is called. Pages is deployed from the job itself, not from a
branch build: a push made with the workflow's `GITHUB_TOKEN` never triggers a
Pages build or another workflow run.

One-time repository setup:

1. **Settings -> Pages -> Source: GitHub Actions.** Do not choose "Deploy from a
   branch"; `deploy-pages` requires the Actions source. Pages is free on public
   repositories; private repositories need a paid plan.
2. **Settings -> Environments -> New environment -> `github-pages`**, add
   yourself as a required reviewer, and restrict deployment branches to `main`.
   This is the publish approval gate. On GitHub Free, environments and
   protection rules exist for public repositories only.
3. Add secrets and variables:

   | Kind | Name | Value |
   | --- | --- | --- |
   | Secret | `GEMINI_API_KEY` | Google AI Studio key, optional |
   | Secret | `BUFFER_API_KEY` | Buffer API key |
   | Variable | `BUFFER_ORGANIZATION_ID` | from `scripts/check_buffer.py` |
   | Variable | `BUFFER_CHANNEL_FB` | Facebook channel id |
   | Variable | `BUFFER_CHANNEL_IG` | Instagram channel id |
   | Variable | `PUBLIC_IMAGE_BASE_URL` | `https://<owner>.github.io/<repo>/posts` |
   | Variable | `ENABLE_QUEUEING` | leave unset, then `true` when ready |
   | Variable | `GEMINI_MODEL` | optional, default `gemini-3.8-flash` |

Dispatch `queue` from `main`: the publish job pushes the image and ledger back
to the branch it runs on. Branch protection that blocks bot pushes will break
the ledger step; allow the Actions bot or commit the ledger yourself.

Scheduled workflows can start late and GitHub disables schedules after about 60
days of repository inactivity. A manual dispatch re-enables them.

## Hosting the image

`PUBLIC_IMAGE_BASE_URL` is any public HTTPS folder that holds one PNG per post,
named `<post_id>.png`. It is not your shop's website and does not need to be.

The workflow uses GitHub Pages:

```
docs/posts/<post_id>.png  ->  https://<owner>.github.io/<repo>/posts/<post_id>.png
```

Pages must be served with the **GitHub Actions** source and a `github-pages`
environment (see above). Each deploy publishes the whole `docs/` folder, so
images are committed to the repository as well as deployed.

Alternatives if you would rather not use Pages:

- your own website folder, e.g. `https://yourdomain.com/social/`,
- Cloudinary or Cloudflare R2 (free tiers, and what Buffer's media guide
  recommends),
- `raw.githubusercontent.com/<owner>/<repo>/main/docs/posts` with no Pages setup
  (works, but GitHub does not intend raw URLs as a CDN).

Whatever the host: public, direct, HTTPS, and stable. Buffer fetches the image
at publish time, so a signed or expiring URL fails silently. Queue mode verifies
the served bytes against the reviewed SHA-256 before anything is queued.

Pages limits: 1 GB site, 100 GB/month soft bandwidth, 10-minute deploy timeout.
The 10 builds/hour limit does not apply to Actions-based deployments. Note that
GitHub's Pages terms say Pages is not for hosting your business or e-commerce
site; a folder of post images is not that, but if you want to stay clearly
inside the rules, use your own hosting or Cloudinary/R2.

## Costs

- GitHub Actions: free for public repositories; private repositories get 2,000
  minutes/month on Free.
- GitHub Pages: free for public repositories.
- Gemini free tier: daily request limits. The writer makes at most 3 attempts.
- Buffer: free plans cap channels and queued posts. The API key page shows
  whether your plan includes API access.
- No paid service is used automatically. If a quota is exhausted the run stops
  and reports it.

## Layout

```
.github/workflows/daily-post.yml   preview -> approval -> image -> queue
assets/fonts/                      Noto Bengali fonts (embedded in the graphic)
assets/photos/                     curated people-free photos + credits.json
config/brand.json                  brand facts, palette, hashtag pools
config/content.json                the 36-idea library, with Bangla copy
config/products.json               optional product catalogue (unused by tips)
config/research.json               legacy research settings (unused)
docs/posts/                        public images served by GitHub Pages
scripts/check_buffer.py            list Buffer organizations/channels
scripts/check_ideas.py             render + validate every idea, contact sheet
scripts/check_photos.py            contact sheet of the photo set, for review
scripts/fetch_photos.py            re-download the photo set (rarely run)
scripts/preview_week.py            generate N local previews
src/content.py                     content loader + daily rotation
src/photos.py                      photo library and tag-matched picking
src/main.py                        pipeline, gates, exit codes
src/config.py                      typed config loading
src/env_file.py                    local .env loader (shell/CI wins)
src/research.py                    legacy RSS research (unused by tips)
src/topic_filter.py                legacy topic filter (unused by tips)
src/writer.py                      Gemini JSON output + offline templates
src/graphics.py                    headless-Chrome renderer + Pillow fallback
src/validator.py                   caption/image/public-URL checks
src/buffer_client.py               Buffer GraphQL client
src/duplicate_guard.py             post ids and retry policy
src/state.py                       atomic JSONL ledger
src/report.py                      markdown run report
state/ledger.jsonl                 publish history (committed)
tests/                             unit + end-to-end tests
out/                               generated artifacts (gitignored)
```

## Still needed from the shop

- Confirm the Taupe hex. I read it from your palette image as `#ADB7B3`; if it is
  different, change it in `config/brand.json`.
- Read a few ideas in `config/content.json` and adjust the wording to your voice.
- Set `verified: true` in `config/brand.json`.
- Buffer account, API key, organization id and the two channel ids (already
  configured in this repo).
- Repo Pages source and the `github-pages` environment (see GitHub Actions).
- Confirm the 10:00 Asia/Dhaka target and daily cadence.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `no usable font found` | Add fonts to `assets/fonts` (Bengali fonts ship there), or install DejaVu fonts |
| `Bengali text needs headless Chrome` | Install Chrome/Edge or set `CHROME_PATH`; Pillow cannot shape Bengali |
| `headless Chrome produced no screenshot` | Usually a stale or locked Chrome profile; rerun, or check `CHROME_PATH` |
| `ZoneInfoNotFoundError` | `pip install tzdata` (already in `requirements.txt`) |
| `no reviewed post for this date` | Run `--mode preview` first; queue mode never regenerates content |
| `image on disk does not match post.json` | Something edited the PNG; rerun preview |
| `photo missing for ...` | A file listed in `credits.json` is gone; run `scripts/fetch_photos.py` |
| `public image check failed` | Pages has not deployed yet, or the URL serves different bytes |
| `buffer: Buffer rejected the API key` | Create a new key at `https://publish.buffer.com/settings/api` |
| `channel id ... not found` | Re-run `python scripts/check_buffer.py`; ids differ per organization |
| `outcome unknown` | Check Buffer manually. Do not delete the ledger line until you know |
| Queueing skipped | Read the gate list in `report.md`; the reason is always printed |
