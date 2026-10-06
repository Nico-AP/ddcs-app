# TikTok scraper

This section describes how video metadata is scraped from the public TikTok
website, what is stored, how captions (transcripts) are collected, and how to
run and diagnose the scraper.

The code lives in [`ddcs/metadata/scraper`](../ddcs/metadata/scraper). For how
the scraped models relate to the rest of the metadata registry, see
[4_metadata.md](4_metadata.md).


## Purpose and scope

The Research API only returns videos of monitored users and keywords. Videos
that enter the database another way, mainly through data donations, have no
Research API details. The scraper fills that gap by loading the public video
page on tiktok.com and reading the data embedded in it.

| Scraped                                              | Not scraped                                                  |
|------------------------------------------------------|--------------------------------------------------------------|
| Videos **without** Research API infos                | Videos the Research API already delivered                    |
| The video's metadata, statistics and original caption | Video files, cover images, comments                          |
|                                                      | User pages (the code can fetch them, but nothing uses it)    |
|                                                      | Translated captions and creator-written caption files        |

The scraper is **off by default**. Nothing is queued or scraped until
`TIKTOK_SCRAPER_ENABLED` is set.


## How a video gets scraped

```
donation / management command        hourly Celery task
            │                                │
            ▼                                ▼
     ScrapeTarget (queue)  ──────►  ScraperService.scrape_batch
                                             │
                    ┌────────────────────────┼─────────────────────────┐
                    ▼                        ▼                         ▼
           video page (1 request)   caption file (0–1 request)   store + mark target
```

### 1. Queueing

A video is scraped only if it has a `ScrapeTarget` row. Rows are created in two
ways, both through `ddcs.metadata.scraper.service`:

- **New donations.** `register_donation_metadata` queues the watch-history and
  liked videos of every incoming donation.
- **Existing videos.** A one-off management command queues videos that were
  already in the database:

  ```
  python manage.py enqueue_scrape_targets [--origin DONATION] [--limit N] [--dry-run]
  ```

  It walks the videos of one data origin (default `DONATION`) and is safe to
  re-run.

In both cases videos that already have Research API infos are skipped, and a
video that is already queued is left untouched.

### 2. Order: newest first

Videos disappear from TikTok over time, so the queue is worked off **newest
publish date first**. The publish time is not looked up anywhere: it is encoded
in the TikTok ID and derived with
[`infer_publication_date_from_id`](../ddcs/metadata/utils.py) when the target is
created (`ScrapeTarget.inferred_create_time`). This works for donated videos,
whose `TikTokVideo.inferred_create_time` is empty.

### 3. The task

`ddcs.metadata.scraper.tasks.scrape_pending_videos` runs hourly at minute 15.

- One run takes up to `TIKTOK_SCRAPER_BATCH_SIZE` targets (default 3000) and
  waits `TIKTOK_SCRAPER_RATE_DELAY` seconds (default 1) between requests.
- A Redis lock ensures only one run is active; a run that finds the lock held
  skips.
- A run stops starting new videos about 50 minutes in. Whatever is left stays
  queued for the next run.
- Targets whose video received Research API infos in the meantime are marked
  `covered_by_api` and skipped.

### 4. Outcome per target

| `ScrapeTarget.status` | Meaning                                                                          | Retried? |
|-----------------------|----------------------------------------------------------------------------------|----------|
| `pending`             | Waiting. Also what a target stays when TikTok blocked the request.               | yes      |
| `success`             | Infos and statistics stored, `TikTokVideo.scraped_at` set.                       | no       |
| `unavailable`         | TikTok reports the video as gone or private (`tiktok_status_code`).              | no       |
| `covered_by_api`      | The Research API delivered the video before it was scraped.                      | no       |
| `failed`              | Anything else: network error, unexpected page structure, data that can't be stored. | after 6 hours, at most `TIKTOK_SCRAPER_MAX_ATTEMPTS` times |

**Blocking.** HTTP 403 or 429 from TikTok counts as a block. The scraper
fetches fresh cookies and retries that video once. Three blocked videos in a
row abort the run and log an error (which emails the admins); the targets stay
`pending`.


## What is stored

All writes go through `ScraperService`. Fields that the Research API also
provides have the **same name, type and value format** as on the Research API
models, so both sources can be read the same way.

### `VideoInfosScraped` (one row per successful scrape)

| Field                                             | Shared with `APIVideoInfos` | Notes |
|---------------------------------------------------|:---------------------------:|-------|
| `description`                                     | ✓ | |
| `create_time`                                     | ✓ | Publish time as reported on the page |
| `duration`                                        | ✓ | Seconds |
| `video_mention_list`                              | ✓ | Mentions as written in the description, without "@". Checked against Research API rows of the same videos: identical. |
| `effect_list`                                     | ✓ | Stored as scraped. **Not** compared with the Research API's format (no sample video with effects was available). |
| `voice_to_text`                                   | ✓ | Text of the original-language caption, see [Captions](#captions) |
| `caption_status`, `caption_vtt`, `caption_language`, `caption_is_auto_generated` | | See [Captions](#captions) |
| `location_created`                                | | Where the video was made. Not the same thing as the API's `region_code`. |
| `text_language`, `category_type`                  | | |
| `is_ad`, `is_aigc`, `aigc_description`            | | |
| `original_item`, `official_item`, `private_item`  | | |
| `diversification_id`, `diversification_labels`    | | |
| `height`, `width`                                 | | |
| `raw`                                             | | See below |

The Research API fields `region_code`, `is_stem_verified` and `video_label`
have no scraped counterpart.

**`raw`** holds the complete video object from the page
(`__DEFAULT_SCOPE__` → `webapp.video-detail` → `itemInfo` → `itemStruct`) with
two things removed: every URL value (they are signed and expire) and the
per-bitrate encoding blocks (`bitrateInfo`, `PlayAddrStruct`). TikTok changes
this structure without notice; keeping it means fields we don't map today can
be recovered later without scraping again. Nothing outside `itemStruct` is
stored.

### `VideoStatisticsScraped` (one row per successful scrape)

| Field                                                                         | Shared with `APIVideoStatistics` |
|-------------------------------------------------------------------------------|:--------------------------------:|
| `view_count`, `like_count`, `comment_count`, `share_count`, `favorites_count` | ✓ |
| `repost_count`                                                                | |

### Changes to `TikTokVideo`

On success the service sets `scraped_at` and fills in `user`, `music` and
`inferred_create_time` and adds hashtags, **only where they are empty**. It
never replaces a value another source has set. Users, music and hashtags it
has to create get `added_by = SCRAPER`.


## Captions

### What a caption is

A caption is TikTok's transcript of what is spoken in a video. It is a small
text file in WebVTT format: a list of timed cues.

```
WEBVTT

00:00:00.400 --> 00:00:01.600
Hallo zusammen

00:00:02.200 --> 00:00:03.520
heute geht es um die Wahl
```

A video can have several caption files: the transcript in the spoken language,
machine translations into other languages, and sometimes a file written by the
creator. Many videos have none.

### What is collected

Only the **original-language** caption, one file per video.

| Collected                                  | Not collected                                     | Why not |
|--------------------------------------------|---------------------------------------------------|---------|
| The caption flagged as original, in WebVTT | Machine translations (e.g. English)               | Derived from the original; each would cost another request |
|                                            | Creator-written files (`creator_caption` format)  | Different format, not examined |

### Where it comes from

The video page does not contain the transcript, only links to the files:

- `itemStruct.video.claInfo.captionInfos`: one entry per caption with
  `language`, `captionFormat`, `isOriginalCaption`, `isAutoGen` and `url`.
- `itemStruct.video.subtitleInfos`: a second listing of the same files (not
  used).

**Selection rule** (`TikTokParser.select_original_caption`): the first
`captionInfos` entry with `isOriginalCaption` true, `captionFormat` equal to
`webvtt`, and a `url`. If there is none, the video counts as having no caption
and no request is made.

The file is then downloaded with one additional request
(`TikTokScraper.fetch_original_caption`), after the usual rate-limit delay.

### What is stored

| Field                       | Content |
|-----------------------------|---------|
| `caption_status`            | What happened, see below |
| `voice_to_text`             | The spoken text as one line: cue texts joined with single spaces, without header, timestamps, cue identifiers or inline markup (`TikTokParser.webvtt_to_text`) |
| `caption_vtt`               | The file exactly as downloaded, including timestamps |
| `caption_language`          | TikTok's language tag of the caption, e.g. `deu-DE` |
| `caption_is_auto_generated` | TikTok's `isAutoGen` flag, see the caveat below |

| `caption_status` | Meaning |
|------------------|---------|
| `fetched`        | Caption downloaded and stored |
| `none_available` | The video has no original-language WebVTT caption |
| `failed`         | The video has one, but the download failed |
| `not_requested`  | Caption collection was switched off when the video was scraped |

The caption links themselves are not stored (they are removed from `raw` like
every other URL). The listing without links stays in `raw`, so it remains
visible which other captions a video had.

### Relation to the Research API's `voice_to_text`

`voice_to_text` on `VideoInfosScraped` is the same content in the same format
as `APIVideoInfos.voice_to_text`. This was checked on 2026-10-06 against six
videos (three German, three Arabic) that have both: the text derived from the
scraped caption was **identical**, character for character, to the Research
API value. Six videos is a small sample; treat the two as equivalent, but not
as guaranteed to match in every case.

### Limits

- **No backfilling.** Caption links are signed and expire about two to three
  days after the page was loaded. A caption can only be collected while the
  video is being scraped. Videos scraped while the feature was off
  (`not_requested`) or whose download failed (`failed`) do not get a caption
  later unless the video is scraped again, which the queue does not do.
- **Coverage.** Videos without speech, and many others, have no caption. How
  large the share is has not been measured.
- **Quality.** The transcripts are produced by speech recognition and contain
  recognition errors. The language TikTok detects can be wrong.
- **`caption_is_auto_generated` is not a quality indicator.** In the videos
  examined, the original transcripts carried `isAutoGen: false` although they
  are evidently machine transcripts, while machine translations carried
  `true`. The flag seems to mark translations, not human-written text.

### Cost

Each captioned video needs two requests instead of one. With the request rate
unchanged, a run that mostly meets captioned videos gets through about half as
many videos. To collect metadata only, set `TIKTOK_SCRAPER_FETCH_CAPTIONS` to
false.

### Failure handling

A caption problem never fails the video. The video's metadata and statistics
are stored, the target becomes `success`, and `caption_status` is `failed`.
Failed downloads are not retried.

Caption files are served from a different host (a TikTok CDN) than the video
pages. If that host starts refusing requests, video scraping continues and the
run does **not** abort; the sign is a high `captions_failed` count in the
task's log line. Whether that host applies its own rate limits is not known.

### Data protection

A transcript is what a person said in a video. It is more personal than counts
and flags and should be handled like the Research API's `voice_to_text`:
covered by the project's data protection and ethics framing, and not passed on
more freely than that field.


## Configuration

All settings are read from the environment (see `.env.example`).

| Setting                         | Default | Effect |
|---------------------------------|---------|--------|
| `TIKTOK_SCRAPER_ENABLED`        | `False` | Master switch. While off, donations queue nothing and the task returns immediately. |
| `TIKTOK_SCRAPER_RATE_DELAY`     | `1.0`   | Seconds between two requests (video pages and caption files alike) |
| `TIKTOK_SCRAPER_BATCH_SIZE`     | `3000`  | Maximum number of videos per run |
| `TIKTOK_SCRAPER_MAX_ATTEMPTS`   | `3`     | Attempts before a failing video is given up on |
| `TIKTOK_SCRAPER_FETCH_CAPTIONS` | `True`  | Also download the original-language caption |
| `CELERY_TIKTOK_SCRAPER_QUEUE`   | default queue | Celery queue for the scraping task. A run can occupy a worker for close to an hour, so a separate queue with its own worker is advisable. |

The hourly schedule entry is `scraper-scrape-pending-videos` in
`CELERY_BEAT_SCHEDULE`. The beat schedule is stored in the database: on an
existing deployment the entry has to be added once in the Django admin
(Periodic tasks).


## Operating it

### First run in production

Behaviour from the production server's network has not been tested; TikTok may
treat it differently from a development machine. Start small:

1. Set `TIKTOK_SCRAPER_ENABLED=True` and deploy (migrations included).
2. Queue a few videos: `python manage.py enqueue_scrape_targets --limit 50`.
3. Run one batch by hand and look at the returned statistics:

   ```python
   from ddcs.metadata.scraper.tasks import scrape_pending_videos
   scrape_pending_videos(max_videos=50)
   ```

4. If the result looks right, queue the backlog (`enqueue_scrape_targets`
   without `--limit`) and add the periodic task.

### Reading a run's statistics

The task logs and returns one dictionary per run:

| Key                | Meaning |
|--------------------|---------|
| `scraped`          | Videos stored |
| `unavailable`      | Videos TikTok reports as gone or private |
| `failed`           | Videos that failed for another reason |
| `blocked`          | Requests TikTok refused |
| `covered_by_api`   | Targets skipped because the Research API has the video now |
| `captions_fetched` | Captions stored |
| `captions_failed`  | Captions that exist but could not be downloaded |
| `aborted`          | `True` if the run stopped after three blocks in a row |

### Where to look

- **Metadata dashboard** (`/metadata/dashboard/`): the "Scraper queue" card
  shows the number of targets per status and the time of the last success.
- **Admin → Scrape targets**: every target with status, attempts, last error
  and TikTok's status code. Read-only.
- **Admin → TikTok videos**: scraped infos and statistics appear as inlines on
  the video.

### Tests

The scraper's tests run offline as part of `python manage.py test`. Tests that
send real requests to tiktok.com are skipped unless asked for:

```
TIKTOK_LIVE_TESTS=1 python manage.py test ddcs.metadata.scraper
```

They rely on specific public videos still existing and will start failing when
those are removed.


## Known unknowns

- **Production network.** Everything was verified from a development machine.
  Whether TikTok serves the same data to the production server, and at what
  request rate it starts blocking, is untested.
- **`effect_list`.** Stored as scraped; its format has not been compared with
  the Research API's.
- **Caption host limits.** Not known whether the CDN serving caption files
  rate-limits separately.
- **Caption coverage.** The share of videos with an original-language caption
  has not been measured.
- **Stability.** The page structure is undocumented and can change at any
  time. A change shows up as a rising number of `failed` targets with
  `TikTokDataExtractionError` or `TikTokMissingRehydrationDataError`.
