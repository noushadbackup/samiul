# Bangla / Banglish Social-Media Research Collector

Collects **real, publicly available** Bangla, Banglish and Bangla-English mixed
comments/posts from YouTube, Facebook, Instagram and TikTok, using **official
APIs only**, for an academic research dataset.

* No synthetic data, no paraphrasing, no fabricated values: missing metadata is stored as `null`.
* `comment_text` is the exact public text. Only invalid Unicode and control characters are removed.
* No login walls, private content, CAPTCHA solving, IP rotation or fingerprint evasion.
  Rate limits and quotas are respected: when a platform says stop, that connector stops.
* Usernames are never stored. Author IDs are HMAC-hashed with a secret salt.
* Every accepted row is traceable through `platform`, `post_id`, `comment_id`, `source_url` and `collected_at`.

---

## 1. Project layout

```
bangla_social_scraper/
  run.py                     CLI (discover / collect / resume / stats / export / batches / check)
  config.yaml                all settings: domains, keywords, limits, filters
  .env.example               credentials template (copy to .env)
  requirements.txt
  core/        config.py, logging_setup.py, models.py, pipeline.py, collector.py, stats.py
  scraper/     base.py, http.py (rate limiting/backoff), youtube.py, facebook.py,
               instagram.py, tiktok.py, meta_common.py
  discovery/   source_discovery.py, keyword_manager.py
  processing/  language.py, quality.py, dedup.py, anonymize.py, normalize.py, lexicons/
  storage/     database.py (SQLite state), exporter.py (CSV/JSONL/Parquet + raw log)
  keywords/    optional <domain>.txt keyword files
  data/raw/ data/accepted/ data/rejected/   outputs (git-ignored)
  logs/        structured JSON logs: collection_YYYY_MM_DD.log
  checkpoints/ SQLite state DB (scraper_state.sqlite3) + fallback anon salt
  tests/       unit + mocked end-to-end tests (MOCK data only)
```

## 2. Installation

```bash
cd bangla_social_scraper
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # then edit .env
python -c "import secrets; print(secrets.token_hex(32))"   # paste into ANON_SALT in .env
python -m pytest -q                  # 68 tests, all offline, MOCK data only
python run.py check                  # shows which platforms have credentials
```

Python 3.10+ is required. Tested with 3.13.

## 3. API setup (legitimate access only)

| Platform  | What you need | Env vars |
|-----------|---------------|----------|
| YouTube   | Google Cloud project → enable **YouTube Data API v3** → Credentials → **API key**. Free quota: 10,000 units/day. | `YOUTUBE_API_KEY` |
| Facebook  | Meta developer app. Either **Page Public Content Access** (requires App Review) or a **Page access token** for Pages you manage. | `FACEBOOK_ACCESS_TOKEN` |
| Instagram | Instagram **Business/Creator** account linked to a Facebook Page, and a Meta app with `instagram_basic` plus Instagram Public Content Access (for hashtag search). | `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ACCOUNT_ID` |
| TikTok    | Approved **TikTok Research API** application (academic researchers) → client key/secret. | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` |

YouTube API key, step by step:
1. https://console.cloud.google.com/ → create or select a project.
2. *APIs & Services → Library* → search "YouTube Data API v3" → **Enable**.
3. *APIs & Services → Credentials → Create credentials → API key*.
4. Recommended: *Restrict key → API restrictions → YouTube Data API v3*.
5. Put it in `.env` as `YOUTUBE_API_KEY=...`.

Each connector is independent. Disable one with `sources.<platform>.enabled: false`.
A connector without credentials is skipped and the others still run.

## 4. `.env` configuration

```dotenv
ANON_SALT=<64 hex chars; keep secret; never change during a project>
YOUTUBE_API_KEY=<your key>
FACEBOOK_ACCESS_TOKEN=
INSTAGRAM_ACCESS_TOKEN=
INSTAGRAM_BUSINESS_ACCOUNT_ID=
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
```

If `ANON_SALT` is empty, a random salt is generated once in `checkpoints/anon_salt.key`.
Back it up: if it is lost, the same author will get a different anonymous ID.

## 5. Commands

```bash
# discover sources only (YouTube: each step = 1 search = 100 quota units)
python run.py discover --domain sports --platform youtube --steps 3

# TEST RUNS — do these first and inspect data/accepted/sports_001.csv
python run.py collect --platform youtube --domain sports --target 50
python run.py collect --domain sports --target 100 --resume     # extends the same batch to 100

# first 1000 samples (new batch sports_002 unless you --resume the test batch)
python run.py collect --platform youtube --domain sports --target 1000
# all enabled platforms, round-robin; failing platforms are skipped
python run.py collect --platform all --domain sports --target 1000

# resume after a stop / quota exhaustion / Ctrl-C
python run.py collect --domain sports --target 1000 --resume    # latest unfinished batch of the domain
python run.py resume --batch sports_001                         # a specific batch

python run.py stats  --batch sports_001            # add --json for machine-readable output
python run.py export --batch sports_001 --output sports_round1 --formats csv,jsonl,parquet
python run.py batches                              # list all batches

# override keywords or the output name for one batch
python run.py collect --platform youtube --domain music --target 500 \
    --keywords "bangla gaan,বাংলা গান" --output music_pilot
```

Exit codes: `0` target reached, `3` stopped before the target (resumable), `2` usage/config error, `130` interrupted.

### Outputs

* `data/raw/<batch>/<platform>.jsonl`: everything fetched, before filtering (already anonymised),
  with `pipeline_status` set to accepted / rejected / deferred.
* `data/accepted/<name>.csv|.jsonl|.parquet`: accepted unique records. The CSV is UTF-8 with a BOM, so Excel shows Bangla correctly.
* `data/rejected/<name>_rejected.csv|.jsonl`: rejected rows with `rejection_reason` and `rejection_detail`.

Columns: `sample_id, platform, domain, record_type, comment_text, post_title, post_text,
context_text, post_id, comment_id, parent_comment_id, source_url, author_anonymous_id,
comment_created_at, post_created_at, like_count, reply_count, collected_at, language,
source_name, source_type, source_id, batch_id`.

Three columns were added beyond the requested list:
* `record_type` = `comment` / `reply` / `post` (Instagram captions).
* `source_id` = the platform channel/page/creator ID.
* `batch_id`.

`context_text` is the parent comment for replies, the post title (or caption when there is no title) for top-level comments, and null for post records.
`sample_id` = platform prefix + SHA-256 of `platform:item_id`, so it is stable and reproducible.

`rejection_reason` is one of: duplicate, near_duplicate, wrong_language, too_low_quality,
spam, empty, emoji_only, invalid_source, missing_text. `rejection_detail` gives specifics such as
`url_only`, `tag_only`, `keyboard_spam`, `repeated_character`, `bot_copy:3_distinct_authors`,
or `pattern:<regex>`.

## 6. How a batch works

1. One batch = one domain. Batch IDs are `<domain>_001`, `<domain>_002`, and so on.
2. The collector rotates round-robin over the selected platforms. Each step is either one discovery
   request (keyword search, rotating to the least-searched keyword) or one page of comments.
3. Every item goes through: clean → language ID → raw log → quality filter → language filter →
   exact dedup → near dedup → store. The DB is committed after every page.
4. The run continues until the number of **accepted** records equals `--target` exactly.
   Rejections never stop collection. Items left over on the last page are *deferred*: they are not
   marked processed and the post's cursor is not advanced, so they stay available.
5. **Diversity caps** are enforced while collecting:
   * per post: `min(max_per_post, ceil(target / min_posts))`, where
     `min_posts = max(min_distinct_posts_floor, ceil(min_distinct_posts_per_1000 × target / 1000))`
   * per creator: `min(max_per_creator, ceil(target / min_distinct_creators))`, never below the per-post cap
   * For target 1000 with defaults: ≤50 per post (≥20 posts) and ≤150 per creator (≥7 creators).
   * For target 50: ≤10 per post and ≤10 per creator.
   If the caps make the target unreachable with the sources found, the batch stops as
   *incomplete* and tells you why. It never pads.
6. A YouTube video is abandoned early when, after 200 processed comments, fewer than 2% were
   accepted (`low_yield_*`). This saves quota on non-Bangla videos.
7. Platform isolation: missing credentials, auth errors, quota exhaustion, persistent rate limits,
   5 consecutive API errors or an unexpected crash each disable **only that platform** for the run.

### Resume guarantees

* `processed_ids` (platform + item ID) means a comment is never processed twice, across restarts and batches.
* Discovery cursors (search page tokens, Graph API `after` cursors, TikTok windows/cursors) live in `crawl_state`.
* Comment cursors are stored per post (`posts.next_cursor`).
* Accepted counts, caps and timing are recomputed from SQLite, so a batch stopped at 637/1000 continues from 637.

## 7. Duplicate detection

Checks run only against **accepted** texts. A rejected comment never blocks a later valid one.
By default (`dedup.scope: global`) the index covers all batches and platforms, so
**cross-platform duplicates** are caught.

1. **Exact duplicate.** SHA-256 of the text after normalising only Unicode (NFC), zero-width
   characters, whitespace, and spacing around punctuation. Case and punctuation are kept.
   → `duplicate`.
2. **Skeleton match.** SHA-256 of a casefolded skeleton with punctuation, whitespace, emoji and
   zero-width characters removed, and letter runs collapsed (`!!!!`/`ooooo`).
   `এই লোকটা একদম বোকা`, `এই লোকটা একদম বোকা।` and `এই লোক টা একদম বোকা` all become
   `এইলোকটাএকদমবোকা`. → `near_duplicate`.
3. **MinHash-LSH.** Character 3-gram shingles of the skeleton, 128-permutation MinHash, 32 bands × 4 rows,
   with buckets stored in SQLite (`lsh_bands`). Candidates are **verified by exact Jaccard
   similarity ≥ 0.80** before rejecting (`rejection_detail` records the similarity).
   This catches small edits ("... অভিনন্দন জানাই" vs "... অভিনন্দন জানাই ভাই").
   Texts shorter than 12 skeleton characters use only layers 1–2, because n-gram similarity is
   unreliable on very short strings and would wrongly merge distinct short insults or reactions.
4. **Copy-paste / bot texts.** If the same text (or a near copy) is posted by ≥ 3 distinct anonymous
   authors and is ≥ 25 characters long, the original accepted row is **retroactively rejected**
   as `spam` (`bot_copy:N_distinct_authors`). Collection then continues to refill the target.

The stored text is never modified for dedup. The normalised forms are used only for hashing.
All thresholds are in `config.yaml` under `dedup:` and `quality:`. Changing the LSH parameters
rebuilds the index automatically.

## 8. Language identification

Rule-based and transparent (`processing/language.py`). Generic language-ID models do not handle
romanised Bangla.

* Bengali script (U+0980–09FF), Latin and other scripts are counted exactly. URLs, @mentions,
  #hashtags and timestamps are ignored.
* `bangla`: Bengali script with < 15% Latin-word tokens.
* `mixed`: Bengali script with ≥ 15% Latin words, or Latin-script Banglish where English words make up ≥ 50% of the lexicon hits.
* `banglish`: Latin script with romanised-Bangla vocabulary (`processing/lexicons/banglish.txt`,
  about 450 words with spelling variants; add more in `banglish_extra.txt`), plus suffix heuristics.
* `english`: Latin script with English vocabulary and no Banglish evidence.
* `other`: other scripts dominate (Hindi, Urdu, Arabic …), Hinglish (`hinglish.txt` markers), or no signal.
* Accepted by default: `bangla, banglish, mixed`. Edit `language.accept` to change this.

## 9. Quality filter

Rejected: missing/empty, emoji-only, punctuation-only, URL-only, tag-only (@/#), fewer than
`min_characters` letters (default 3), one repeated character (`কককককক`, `hhhhh`), keyboard mashing
(`asdfghjkl`), advertising/promo spam (editable regex list incl. Bangla patterns and BD phone numbers),
links combined with promo words, and copy-paste bot texts (see above).
**Short comments are kept.** `শালা হারামি`, `ভাই`, `valoooo`, `হা হা হা` all pass.
Profanity is never removed.

## 10. Rate limiting

`scraper/http.py`: per-platform minimum delay between requests, timeouts, bounded retries with
exponential backoff and jitter, `Retry-After` honoured, and per-platform rate-limit and quota detection.
Local budgets: YouTube `daily_quota_units` (Pacific-time day, like Google), TikTok
`daily_request_budget`. When a quota is hit the platform stops and the batch can be resumed later.

## 11. Known limitations per platform

**YouTube**
* Quota: `search.list` costs 100 units, so the default 10,000 units/day allows about 90 searches.
  Comment pages cost 1 unit per 100 comments. 1,000 accepted Bangla comments typically need a few
  searches plus 30–150 comment pages, depending on Bangla density.
* `textOriginal` is used. Where the API omits it, `textDisplay` with `textFormat=plainText` is used.
  Replies often begin with `@handle` (kept verbatim; set `privacy.mask_mentions_in_export: true` to mask in exports).
* Only up to 5 replies per thread unless `fetch_all_replies: true` (costs extra quota).
* Videos with comments disabled are skipped. Shorts are not distinguished from normal videos (`source_type = youtube_video`).
* Search results depend on Google's ranking and change over time. Discovery cursors make a batch reproducible as recorded, but not re-runnable to identical results.

**Facebook**
* Requires Page Public Content Access (App Review) or a Page token. Without either, nothing can be collected legitimately.
* Pages Search also requires PPCA. Without it only `sources.facebook.pages.<domain>` is used, so you must list public pages.
* The commenter ID (`from`) is returned only to Page tokens, so `author_anonymous_id` is often null and bot/copy detection is weaker.
* Personal profiles and groups are not supported (not legitimately accessible).
* Meta's research route for scale is the Meta Content Library (via ICPSR/SOMAR). It runs in a controlled environment and is not automated here.

**Instagram**
* The Graph API does **not** expose comments on media you do not own. For third-party public
  posts/reels only the **caption** is collected (`record_type = post`). Comments are collected only
  for your own account's media (`collect_own_media_comments: true`).
* Hashtag search is limited to 30 unique hashtags per 7 days per account. Hashtag results do not
  identify the owner, so `source_id` is null and the per-creator cap cannot be applied to them.
* Business Discovery works only for Business/Creator accounts.

**TikTok**
* Only the Research API is used, and it requires an approved academic application. Without approval the connector is disabled.
* 1,000 requests/day. Video search uses 30-day windows over `lookback_days`.
* Comment authors are not returned, so `author_anonymous_id` is null and bot-copy detection cannot use authors.
* The TikTok Research API terms include data retention/refresh obligations. Check your approval terms before publishing.

**General**
* Language ID is lexicon-based. Expect some errors on very short or ambiguous Latin text.
  Extend `banglish_extra.txt` and validate a sample manually.
* Deleted or edited comments after collection are not tracked (`collected_at` records when the snapshot was taken).
* Platform terms of service and your ethics board's requirements still apply. This tool keeps
  the technical side compliant (official APIs, no evasion), but you remain responsible for use.

## 12. Tests

`python -m pytest -q` runs unit tests and mocked end-to-end tests. These include the real CLI against a local
**mock** YouTube server (`tests/mock_youtube_server.py`). All test data is clearly marked MOCK and is
generated in memory. It never touches `data/` and must never be used as research data.
