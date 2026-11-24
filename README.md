# Khuje Nao - daily Facebook/Instagram automation

A cautious pipeline that produces one winter-clothing post per day for a shop in
Dhaka: research, caption, a branded 1080x1350 graphic, validation, then an
optional Buffer queue.

**Current state: preview works with no credentials.** Publishing stays blocked
until the product facts are verified and Buffer access is configured.

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

`--offline` skips RSS and Gemini and uses an approved fallback topic plus the
template writer. Nothing is queued.

Several days at once:

```powershell
python scripts/preview_week.py --days 7
python scripts/preview_week.py --days 7 --start 2026-11-23
python scripts/preview_week.py --days 7 --online   # RSS + Gemini
```

Offline is the default there so output is repeatable. Each day is a normal
preview run.

## What it does

```
research (Google News RSS)
   -> filter (relevance + blocked topics)
   -> topic (or an approved fallback topic)
   -> caption (Gemini, or deterministic templates when offline)
   -> graphic (Pillow, 1080x1350, text only)
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
| `config/brand.json` | Name, tagline, tone, colours, CTA, caption limits, hashtag pools, banned phrases, timezone (`Asia/Dhaka`), `verified` |
| `config/products.json` | Products with name, category, audience, keywords, `price: null`, `stock: "unknown"`, `verified` |
| `config/research.json` | Search queries, optional RSS feeds, relevance/blocked keywords, approved fallback topics |

The writer may only use facts from these files. It is never allowed to invent
prices, discounts, stock, delivery promises, materials or availability.

### Products

`config/products.json` holds 21 winter items. The first nine are the shop's own
list; the rest are relevant winter pieces added for post variety and reach.

Shop list:

1. Solid Printed Cotton Hoodie
2. Padded Jacket
3. Varsity Jacket
4. Padded Vest Jacket
5. Flannel Check Shacket
6. Denim Shirt / Jacket
7. Full Sleeve Polo Shirt
8. Sweater
9. Sweatshirt

Added for reach: Fleece Jacket, Bomber Jacket, Knit Cardigan, Turtle Neck
Sweater, Thermal Base Layer Set, Thermal Top, Kids Winter Set, Knit Beanie,
Woven Scarf, Knit Gloves, Wool Socks, Ear Muffs.

Delete any item or set `"enabled": false` if you would rather not post about it.

Every entry ships with `price: null`, `stock: "unknown"` and the catalog has
`verified: false`. Nothing here claims a price, stock level, material or
delivery term, and the writer cannot state any of those.

**Queueing refuses to run until a human sets `verified: true` in both
`brand.json` and `products.json`.** Because these posts are for reach and not
for sale, that check is simply "I have read the names and descriptions" - it is
not a stock check.

### Order of operations

1. Preview locally with no credentials (now).
2. Adjust names, descriptions and hashtags until you like the output.
3. Set `verified: true` in `brand.json` and `products.json`.
4. Create the Buffer account, connect Facebook and Instagram, and add the API
   key. This is the point where Buffer details become necessary.
5. Run `python scripts/check_buffer.py`, then a single supervised queue post.
6. Only then add `ENABLE_QUEUEING=true` and both channels.

### Captions, hashtags, graphics

- 80-320 characters, English, 5-10 hashtags.
- One required tag (`#KhujeNao`) plus audience tags, winter tags and Dhaka tags.
  Pools live in `config/brand.json`; the offline writer fills roughly
  1 + 2 audience + 4 winter + 2 local, then adds filler up to the limit.
- Instagram's limit is **2,196 UTF-16 code units**, and a line break counts as
  2. The validator measures the real payload, not `len()`.
- The graphic is text only: no models, no stock photos, and therefore never a
  photo of a woman. Headlines are measured and shrunk; if the text cannot fit,
  rendering fails instead of cropping.

## Safety gates (queue mode)

All of these must pass, or nothing is published:

1. `ENABLE_QUEUEING=true`
2. `brand.json` and `products.json` are verified
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
   | Variable | `GEMINI_MODEL` | optional, default `gemini-2.5-flash` |

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
config/brand.json                  brand facts, caption rules, hashtag pools
config/products.json               product facts
config/research.json               sources, filters, fallback topics
docs/posts/                        public images served by GitHub Pages
scripts/check_buffer.py            list Buffer organizations/channels
scripts/preview_week.py            generate N local previews
src/main.py                        pipeline, gates, exit codes
src/config.py                      typed config loading
src/env_file.py                    local .env loader (shell/CI wins)
src/research.py                    Google News RSS + optional feeds
src/topic_filter.py                relevance, blocked topics, fallback
src/writer.py                      Gemini JSON output + offline templates
src/graphics.py                    Pillow renderer + text fitting
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

- Set `verified: true` in `config/brand.json` and `config/products.json` once you
  are happy with the names and copy.
- Buffer account, API key, organization id and the two channel ids (step 4
  above; not needed for previews).
- Repo owner/name; enable Pages on `main` / `docs`.
- Confirm the 10:00 Asia/Dhaka target and daily cadence.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `no usable font found` | Add `assets/fonts/Inter-Bold.ttf` and `Inter-Regular.ttf`, or install DejaVu fonts |
| `ZoneInfoNotFoundError` | `pip install tzdata` (already in `requirements.txt`) |
| `no reviewed post for this date` | Run `--mode preview` first; queue mode never regenerates content |
| `image on disk does not match post.json` | Something edited the PNG; rerun preview |
| `public image check failed` | Pages has not deployed yet, or the URL serves different bytes |
| `buffer: Buffer rejected the API key` | Create a new key at `https://publish.buffer.com/settings/api` |
| `channel id ... not found` | Re-run `python scripts/check_buffer.py`; ids differ per organization |
| `outcome unknown` | Check Buffer manually. Do not delete the ledger line until you know |
| Queueing skipped | Read the gate list in `report.md`; the reason is always printed |
