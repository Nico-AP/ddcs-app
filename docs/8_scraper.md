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

It does not try to cover every donated video. It scrapes what donors actually
**watched during the study period (2026-07-01 to 2026-09-20)**, starting with
the videos most donors saw.

| Scraped                                                                                   | Not scraped                                                     |
|-------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| Videos in a donor's watch history within the study period, **without** Research API infos | Videos the Research API already delivered                       |
|                                                                                           | Videos only watched outside the study period                    |
|                                                                                           | Videos that were only liked, shared, bookmarked or commented on |
| The video's metadata, statistics and original caption                                     | Video files, cover images, comments                             |
|                                                                                           | User pages (the code can fetch them, but nothing uses it)       |
|                                                                                           | Translated captions and creator-written caption files           |

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

A video is scraped only if it has a `ScrapeTarget` row.

**Which videos are queued.** A video is queued if it appears in the watch
history of at least one donation with a view inside the **watch window**:
2026-07-01 to 2026-09-20, both days included, in UTC (donated timestamps are
parsed as UTC). The window is defined in
[`scraper/config.py`](../ddcs/metadata/scraper/config.py)
(`WATCH_WINDOW_START`, `WATCH_WINDOW_END`). Only the watch-history blueprint
counts, including its backup variants; likes, shares, bookmarks and comments
do not. Videos that already have Research API infos are never queued.

**What is recorded per target.**

| Field              | Meaning                                                                                                                            |
|--------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `occurrence_count` | Number of **donations** whose watch history contains the video within the window. A donor who watched it twenty times counts once. |
| `last_watched_at`  | The most recent view of the video within the window, across all donations                                                          |

**How targets get there.** Two paths, both through
`ddcs.metadata.scraper.service.enqueue_watched_videos`:

- **The retrospective command** goes through all donated watch histories:

  ```
  python manage.py enqueue_watched_videos [--start 2026-07-01] [--end 2026-09-20] [--keep-counts] [--dry-run]
  ```

  It takes the participants that have a successfully extracted watch-history
  donation one at a time, decrypts only that donation, and for every video
  the donor watched in the window raises the video's count by one (or
  creates the target) and keeps the later view.

  Each donation is written to the database before the next one is read.
  Nothing is collected in memory, so the number of donated videos (about 9.5
  million in total) does not affect how much memory the command needs. A
  donation that cannot be read is logged, counted and skipped.

  Because the command **adds** to the counts, it first **resets all counts
  to zero**. A run therefore always counts from scratch and can be repeated;
  a target that no view backs any more (for example after the window was
  narrowed) stays at 0 and at the end of the queue. The status of a target is
  never changed, so nothing that was already scraped is queued again.

  | Option             | Effect                                                                                         |
  |--------------------|------------------------------------------------------------------------------------------------|
  | `--start`, `--end` | Use a different watch window for this run                                                      |
  | `--keep-counts`    | Skip the reset and add to the stored counts. Every donation read is then counted again on top. |
  | `--dry-run`        | Only read the watch histories and print the summary; nothing is reset or written               |

  It ends with a summary:

  ```
  Watch window: 2026-07-01 to 2026-09-20 (UTC, both days included)
  Donations read: 25
  Donations that could not be read: 0
  Views in the window: 2164
  Records skipped (no date or no video ID): 0
  Videos watched in the window, summed over donations: 2097
  Counts reset on existing targets: 0
  Targets created: 652
  Counts raised on existing targets: 1445
  Skipped, Research API has the video (per donation): 0
  ```

  "Summed over donations" counts a video once per donor who watched it, so it
  is an upper bound on the number of distinct videos, which the command does
  not track. A dry run stops after that line.

  If the command is interrupted, the counts are partial. Run it again; the
  reset makes it start over. The scraper can keep running in the meantime: it
  simply works with the counts as they fill in.

- **New donations.** `register_donation_metadata` applies the same rule to
  every incoming donation: each video it shows as watched in the window gets
  its count raised by one (or a new target), and the later view is kept.

**The counts are not exact, by design.** They only rank the queue. A donation
is counted twice if its processing is retried after a later step failed, or
if it arrives while the command is running and is then also read by it.
Running the command again brings the counts back in line.

Videos that have no `TikTokVideo` row yet get one (`added_by = DONATION`).

### 2. Order: widely seen recent videos, then most recent

The queue is worked off in two steps:

1. **Priority group, most donors first.** Targets with an
   `occurrence_count` of at least 15 and a `last_watched_at` on or after
   2026-08-01 (UTC), ordered by count, then most recent view. Videos that
   many donors saw matter most for the study.
2. **Everything else, most recent view first**, whatever the count. The
   videos watched most recently are the most likely to still be online.
   Targets last watched before 2026-08-01 therefore follow after the newer
   ones, and targets without a watch date come last.

The thresholds are defined in
[`scraper/config.py`](../ddcs/metadata/scraper/config.py)
(`PRIORITY_MIN_OCCURRENCES`, `PRIORITY_WATCHED_SINCE`). Below the count
threshold the count plays no role, so a handful of duplicate donations
cannot push a video to the front.

### 3. The task

`ddcs.metadata.scraper.tasks.scrape_pending_videos` is scheduled hourly at
minute 15, and while there is work it runs continuously:

- One run takes up to `TIKTOK_SCRAPER_BATCH_SIZE` targets (default 3000) and
  stops starting new videos about 50 minutes in.
- **Runs follow each other without a gap.** A run that leaves pending targets
  behind queues the next run itself (5 seconds later). The chain ends when the
  queue is empty or a run was aborted.
- The hourly schedule entry is what (re)starts the chain: after the queue was
  empty, after a worker restart, and once a
  [cool-down](#cool-down-after-aborts) has passed.
- A Redis lock ensures only one run is active; a run that finds the lock held
  skips.
- A run started by hand with `max_videos` is a one-off and queues nothing.
- Targets whose video received Research API infos in the meantime are marked
  `covered_by_api` and skipped.

### 4. Pacing

`TIKTOK_SCRAPER_RATE_DELAY` (default 1 second) is the minimum time between the
**starts** of two video-page requests. Time spent loading a page, downloading
its caption and storing the result counts towards that interval, so the
scraper only waits for what is left of it. With the default, the ceiling is
60 videos per minute.

**Jitter.** Each interval is stretched or shortened by a random factor,
`TIKTOK_SCRAPER_RATE_JITTER` (default 0.3, so between 70% and 130% of the
delay). Requests then don't arrive in a perfectly regular rhythm, while the
average rate stays the same. This removes one, fairly weak, sign of
automation. It does not hide the volume of requests, where they come from, or
that they are not made by a browser; do not expect it to prevent blocking.

Caption downloads are **not** paced by default. They go to a different host (a
CDN) than the pages, so slowing them down would not protect the page host.
`TIKTOK_SCRAPER_CAPTION_DELAY` adds a pause before each caption download if
that host turns out to object.

Measured on 2026-10-06 from a development machine, twelve videos of which
eight had a caption: 27 seconds (27 videos/min) with the earlier pacing, where
the delay was added after every request including captions, and 12 seconds
(about 60 videos/min) with the pacing described here. This shows the effect of
the pacing change on a small sample; it is not a production throughput figure.

### 5. Outcome per target

| `ScrapeTarget.status` | Meaning                                                                             | Retried?                                                   |
|-----------------------|-------------------------------------------------------------------------------------|------------------------------------------------------------|
| `pending`             | Waiting. Also what a target stays when TikTok blocked the request.                  | yes                                                        |
| `success`             | Infos and statistics stored, `TikTokVideo.scraped_at` set.                          | no                                                         |
| `unavailable`         | TikTok reports the video as gone or private (`tiktok_status_code`).                 | no                                                         |
| `covered_by_api`      | The Research API delivered the video before it was scraped.                         | no                                                         |
| `failed`              | Anything else: network error, unexpected page structure, data that can't be stored. | after 6 hours, at most `TIKTOK_SCRAPER_MAX_ATTEMPTS` times |

### 6. When TikTok blocks

A run is **aborted** when it looks as if TikTok has stopped serving us. There
are two signs, counted separately:

| Sign                                                                                                                            | Rule              | `abort_reason`         |
|---------------------------------------------------------------------------------------------------------------------------------|-------------------|------------------------|
| TikTok refuses outright: HTTP 403 or 429. The scraper first fetches fresh cookies and retries that video once.                  | 3 videos in a row | `blocked`              |
| Videos fail without a refusal: the page has no data, the data has an unexpected structure, or the request fails on the network. | 5 videos in a row | `consecutive_failures` |

A success or an `unavailable` answer resets both counts, because either one
shows that pages are being served.

**Aborting protects the queue.** The videos in the streak that triggered the
abort stay `pending` and no attempt is counted for them. Failures are only
written as `failed` once a later video shows that scraping still works (or the
run ends with a streak too short to abort on). Without this, a night of being
blocked would use up all three attempts of thousands of targets.

The second rule rests on an assumption: that a "soft" block, where TikTok
answers normally but without the data, shows up as many failures in a row.
What such a block actually looks like on TikTok has **not** been observed. The
rule keys on the pattern, not on the page content, so it also catches the
other likely cause of mass failures: TikTok changing its page structure. In
that case runs keep aborting, the queue is preserved, and the parser needs
fixing.

An abort logs an error (which emails the admins) with the reason and the time
scraping will resume.

#### Cool-down after aborts

After an aborted run, scraping pauses:

| Aborted runs in a row  | Pause    |
|------------------------|----------|
| 1                      | 1 hour   |
| 2                      | 2 hours  |
| 3                      | 4 hours  |
| 4                      | 8 hours  |
| 5                      | 16 hours |
| 6 or more              | 24 hours |

- During the pause, scheduled runs are skipped. The first scheduled run after
  the pause tries again.
- A run that gets at least one success or `unavailable` answer ends the
  cool-down and resets the count. Another abort lengthens it.
- A run started by hand with `max_videos` ignores the pause (it is an explicit
  test), but its result still counts: an abort lengthens the pause, a healthy
  run ends it.
- The state is kept in the cache (Redis) for a week. If the cache is flushed,
  the cool-down is gone and the next scheduled run proceeds.

**Resuming right away.** While a cool-down is active, the metadata dashboard
shows a notice in the "Scraper queue" card with a **Resume scraping now**
button. It ends the cool-down and queues a run. The same from a shell
(`python manage.py shell`):

```python
from ddcs.metadata.scraper.service import clear_cooldown
from ddcs.metadata.scraper.tasks import scrape_pending_videos
clear_cooldown()
scrape_pending_videos.delay()
```

Resuming while TikTok is still blocking leads to another abort and a longer
pause.


## What is stored

All writes go through `ScraperService`. Fields that the Research API also
provides have the **same name, type and value format** as on the Research API
models, so both sources can be read the same way.

### `VideoInfosScraped` (one row per successful scrape)

| Field                                                                             | Shared with `APIVideoInfos` | Notes                                                                                                                 |
|-----------------------------------------------------------------------------------|:---------------------------:|-----------------------------------------------------------------------------------------------------------------------|
| `description`                                                                     |             ✓              |                                                                                                                       |
| `create_time`                                                                     |             ✓              | Publish time as reported on the page                                                                                  |
| `duration`                                                                        |             ✓              | Seconds                                                                                                               |
| `video_mention_list`                                                              |             ✓              | Mentions as written in the description, without "@". Checked against Research API rows of the same videos: identical. |
| `effect_list`                                                                     |             ✓              | Stored as scraped. **Not** compared with the Research API's format (no sample video with effects was available).      |
| `voice_to_text`                                                                   |             ✓              | Text of the original-language caption, see [Captions](#captions)                                                      |
| `caption_status`, `caption_vtt`, `caption_language`, `caption_is_auto_generated`  |  See [Captions](#captions)  |
| `location_created`                                                                |                             | Where the video was made. Not the same thing as the API's `region_code`.                                              |
| `text_language`, `category_type`                                                  |                             |                                                                                                                       |
| `is_ad`, `is_aigc`, `aigc_description`                                            |                             |                                                                                                                       |
| `original_item`, `official_item`, `private_item`                                  |                             |                                                                                                                       |
| `diversification_id`, `diversification_labels`                                    |                             |                                                                                                                       |
| `height`, `width`                                                                 |                             |                                                                                                                       |
| `raw`                                                                             |                             | See below                                                                                                             |

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

| Field                                                                         | Shared with `APIVideoStatistics`  |
|-------------------------------------------------------------------------------|:---------------------------------:|
| `view_count`, `like_count`, `comment_count`, `share_count`, `favorites_count` |                ✓                 |
| `repost_count`                                                                |                                   |

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

| Collected                                  | Not collected                                     | Why not                                                    |
|--------------------------------------------|---------------------------------------------------|------------------------------------------------------------|
| The caption flagged as original, in WebVTT | Machine translations (e.g. English)               | Derived from the original; each would cost another request |
|                                            | Creator-written files (`creator_caption` format)  | Different format, not examined                             |

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

| Field                       | Content                                                                                                                                                        |
|-----------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `caption_status`            | What happened, see below                                                                                                                                       |
| `voice_to_text`             | The spoken text as one line: cue texts joined with single spaces, without header, timestamps, cue identifiers or inline markup (`TikTokParser.webvtt_to_text`) |
| `caption_vtt`               | The file exactly as downloaded, including timestamps                                                                                                           |
| `caption_language`          | TikTok's language tag of the caption, e.g. `deu-DE`                                                                                                            |
| `caption_is_auto_generated` | TikTok's `isAutoGen` flag, see the caveat below                                                                                                                |

| `caption_status` | Meaning                                                        |
|------------------|----------------------------------------------------------------|
| `fetched`        | Caption downloaded and stored                                  |
| `none_available` | The video has no original-language WebVTT caption              |
| `failed`         | The video has one, but the download failed                     |
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

Each captioned video needs two requests instead of one. The caption download
is not paced (see [Pacing](#4-pacing)) and its duration counts towards the
interval between page requests, so with the default settings captions cost
little or no throughput. They do add load on TikTok's CDN. To collect metadata
only, set `TIKTOK_SCRAPER_FETCH_CAPTIONS` to false.

### Failure handling

A caption problem never fails the video. The video's metadata and statistics
are stored, the target becomes `success`, and `caption_status` is `failed`.
Failed downloads are not retried.

Caption files are served from a different host (a TikTok CDN) than the video
pages. If that host starts refusing requests, video scraping continues and the
run does **not** abort; the sign is a high `captions_failed` count in the
run's statistics. Whether that host applies its own rate limits is not known.
If it does, raise `TIKTOK_SCRAPER_CAPTION_DELAY`.

### Data protection

A transcript is what a person said in a video. It is more personal than counts
and flags and should be handled like the Research API's `voice_to_text`:
covered by the project's data protection and ethics framing, and not passed on
more freely than that field.


## Configuration

All settings are read from the environment (see `.env.example`).

| Setting                         | Default       | Effect                                                                                                                                                            |
|---------------------------------|---------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `TIKTOK_SCRAPER_ENABLED`        | `False`       | Master switch. While off, donations queue nothing and the task returns immediately.                                                                               |
| `TIKTOK_SCRAPER_RATE_DELAY`     | `1.0`         | Minimum seconds between the starts of two video-page requests                                                                                                     |
| `TIKTOK_SCRAPER_RATE_JITTER`    | `0.3`         | Random variation of that interval as a fraction (0.3 = ±30%); `0` switches it off                                                                                 |
| `TIKTOK_SCRAPER_CAPTION_DELAY`  | `0.0`         | Seconds to wait before each caption download                                                                                                                      |
| `TIKTOK_SCRAPER_BATCH_SIZE`     | `3000`        | Maximum number of videos per run                                                                                                                                  |
| `TIKTOK_SCRAPER_MAX_ATTEMPTS`   | `3`           | Attempts before a failing video is given up on                                                                                                                    |
| `TIKTOK_SCRAPER_FETCH_CAPTIONS` | `True`        | Also download the original-language caption                                                                                                                       |
| `CELERY_TIKTOK_SCRAPER_QUEUE`   | default queue | Celery queue for the scraping task. While targets are pending the scraper occupies one worker continuously, so a separate queue with its own worker is advisable. |

The schedule entry is `scraper-scrape-pending-videos` in
`CELERY_BEAT_SCHEDULE`. The beat schedule is stored in the database: on an
existing deployment the entry has to be added once in the Django admin
(Periodic tasks).


## Operating it

### First run in production

Behaviour from the production server's network has not been tested; TikTok may
treat it differently from a development machine. Start small:

1. Set `TIKTOK_SCRAPER_ENABLED=True` and deploy (migrations included). Do not
   add the periodic task yet: without it nothing is scraped on its own.
2. See how much there is: `python manage.py enqueue_watched_videos --dry-run`.
   This already reads and decrypts every watch history, so it also shows how
   long that part takes.
3. Fill the queue: `python manage.py enqueue_watched_videos`. Queueing alone
   sends no requests to TikTok.
4. Run one small batch by hand and look at the returned statistics:

   ```python
   from ddcs.metadata.scraper.tasks import scrape_pending_videos
   scrape_pending_videos(max_videos=50)
   ```

5. If the result looks right, add the periodic task.

Re-run `enqueue_watched_videos` from time to time to bring the counts back in
line (see [Queueing](#1-queueing)).

### Reading a run's statistics

The task logs and returns one dictionary per run. The most recent run is also
shown on the metadata dashboard ("Scraper queue" card) for about a day:

| Key                 | Meaning                                                                                      |
|---------------------|----------------------------------------------------------------------------------------------|
| `scraped`           | Videos stored                                                                                |
| `unavailable`       | Videos TikTok reports as gone or private                                                     |
| `failed`            | Videos that failed for another reason                                                        |
| `blocked`           | Requests TikTok refused                                                                      |
| `covered_by_api`    | Targets skipped because the Research API has the video now                                   |
| `captions_fetched`  | Captions stored                                                                              |
| `captions_failed`   | Captions that exist but could not be downloaded                                              |
| `aborted`           | `True` if the run stopped because TikTok appears to be blocking                              |
| `abort_reason`      | `blocked`, `consecutive_failures`, or empty; see [When TikTok blocks](#6-when-tiktok-blocks) |
| `seconds`           | Wall time of the run                                                                         |
| `videos_per_minute` | Videos a page was requested for, per minute, whatever the outcome                            |

`videos_per_minute` is the number to watch when tuning: it should sit just
below `60 / TIKTOK_SCRAPER_RATE_DELAY`. If it is clearly lower, page loads are
slower than the delay and lowering the delay will not help.

### Where to look

- **Metadata dashboard** (`/metadata/dashboard/`): the "Scraper queue" card
  shows the number of targets per status, the time of the last success and the
  last run's statistics. While scraping is paused after aborts it also shows
  until when, and how to resume immediately.
- **Admin → Scrape targets**: every target with status, donor count, last
  watch date, attempts, last error and TikTok's status code, in queue order.
  Read-only.
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
- **Duration of the retrospective run.** `enqueue_watched_videos` needs
  little memory whatever the data size, but its run time on the production
  data (about 9.5 million donated videos) is not measured. It was run
  against a development database with 25 donations.
- **What a soft block looks like.** Not observed. The abort on consecutive
  failures assumes it shows up as many failed videos in a row.
- **Production throughput.** No figures yet. Fill them in from the
  `videos_per_minute` of the first production runs before changing the delay
  or adding concurrency.
- **`effect_list`.** Stored as scraped; its format has not been compared with
  the Research API's.
- **Caption host limits.** Not known whether the CDN serving caption files
  rate-limits separately.
- **Caption coverage.** The share of videos with an original-language caption
  has not been measured.
- **Stability.** The page structure is undocumented and can change at any
  time. A change shows up as runs aborting with `consecutive_failures` while
  TikTok is otherwise reachable.
