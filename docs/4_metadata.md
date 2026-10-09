# Documentation of TikTok Metadata Enrichment

TikTok metadata enrichment is handled by the `ddcs.metadata` app.

We use two sources to enrich metadata:

1. TikTok's Research API
2. Information scraped from TikTok


## How metadata is stored

To honor that information may come from different sources and make it retraceable,
we use a database design that distinguishes between *Base/Registry Models*,
models capturing *Research API information*, models capturing *scraped information*
and models capturing *donation information*.

### Base/Registry Models (`ddcs.metadata.models`)

These models serve as the inventory of registered TikTok objects of
interest for this project.

TikTok objects of interest are currently:

- Videos (`TikTokVideo`)
- Users (`TikTokUser`)
- Music (`TikTokMusic`)
- Hashtags (`TikTokHashtag`)

These models only hold the unique TikTok identifier (usually the ID supplied by TikTok
or for users the unique username) and meta information on whether an object should be
monitored and to which other objects they are related. Actual information retrieved
through the API or through scraping is stored on the respective information models
(see below).

Different sources can add objects to the registry — see [Data origins](#data-origins)
for the full table:

- **Imports** — seed objects for monitoring, populated via management commands
  (see [Populating the registry](#populating-the-registry)).
- **Donations** — videos and users discovered in received data donations.
- **Research API** — new objects discovered in payloads returned by the API.
- **Scraper** — new objects discovered in scraped data.


### Research API Information Models (`ddcs.metadata.research_api.models`)

Each base/registry model has one or more companion models that hold the actual
fields returned by TikTok's Research API. Two policies coexist:

| Model                | Parent          | Policy                                      |
|----------------------|-----------------|---------------------------------------------|
| `APIVideoInfos`      | `TikTokVideo`   | Created once per parent (latest = first).   |
| `APIVideoStatistics` | `TikTokVideo`   | **Append-only history** — one row per sync. |
| `APIUserInfos`       | `TikTokUser`    | Created once per parent.                    |
| `APIUserStatistics`  | `TikTokUser`    | Append-only history.                        |
| `APIMusicInfos`      | `TikTokMusic`   | Created once per parent.                    |
| `APIHashtagInfos`    | `TikTokHashtag` | Created once per parent.                    |

The split is intentional: "infos" fields are stable identity-style metadata (a
video's description, region code, duration). "Statistics" fields are inherently
time-varying counts and we thus track the full trajectory.

All writes go through `ResearchAPIService`
([`ddcs.metadata.research_api.service`](../ddcs/metadata/research_api/service.py)).
Do not create these rows directly from views, signals, or other services — the
service is the single ingestion path so that `sync_stats`, idempotency, and the
above policies stay consistent.


### Scraped Information Models (`ddcs.metadata.scraper.models`)

Companion models for fields obtained by scraping the public TikTok website:

- `VideoInfosScraped` → `TikTokVideo` (one row per successful scrape)
- `VideoStatisticsScraped` → `TikTokVideo`
- `ScrapeTarget` → `TikTokVideo` (one-to-one): the scraping queue

The scraper enriches **videos that have no Research API infos** and that donors
watched, liked or bookmarked during the study period (2026-07-01 to
2026-09-20), starting with the videos most donors interacted with. It also collects each video's original-language
caption. It is off unless `TIKTOK_SCRAPER_ENABLED` is set.

Fields that both sources provide have the same name, type and value format as
on the Research API models, so the two can be read interchangeably:

| Model                    | Shared with the Research API model                                                             |
|--------------------------|------------------------------------------------------------------------------------------------|
| `VideoInfosScraped`      | `description`, `create_time`, `duration`, `video_mention_list`, `effect_list`, `voice_to_text` |
| `VideoStatisticsScraped` | `view_count`, `like_count`, `comment_count`, `share_count`, `favorites_count`                  |

All writes go through `ddcs.metadata.scraper.service`. On success the service
also fills in `user`, `music`, `inferred_create_time` and adds hashtags on the
`TikTokVideo`, but only where they are empty; it never replaces values set by
another source.

The full description (queueing, outcomes, every stored field, captions,
configuration, operation and known limits) is in
[8_scraper.md](8_scraper.md).

Scrapers running elsewhere can work on the same queue through the API: they
claim videos that are missing metadata and submit what they scraped, which is
stored through the same service. See
[8_scraper.md → External scrapers](8_scraper.md#external-scrapers).


### Donation Information Models (`ddcs.metadata.donations.models`)

Donations are stored encrypted, so the database cannot be asked which videos
donors interacted with. The companion model for what donations tell about a
video keeps that fact:

- `DonationVideoInfos` → `TikTokVideo` (one-to-one): one row per video that at
  least one donation shows as **watched, liked or bookmarked** (shares and
  comments do not count).

| Field                           | Meaning                                                                                                     |
|---------------------------------|-------------------------------------------------------------------------------------------------------------|
| `watched_count`                 | Number of donations whose watch history contains the video. A donor who watched it twenty times counts once. |
| `liked_count`                   | Number of donations whose liked videos contain it                                                           |
| `bookmarked_count`              | Number of donations whose bookmarked videos contain it                                                      |
| `last_interaction_at`           | Most recent view, like or bookmark across all donations; empty if none of them has a readable date          |
| `last_interaction_in_window_at` | The same within the study period (2026-07-01 to 2026-09-20, UTC); empty if there is none                    |

Unlike `added_by`, a row exists for every such video, whichever source
registered the video first. Unlike `ScrapeTarget`, it also covers videos the
Research API delivered, videos that were liked or bookmarked but not watched,
and interactions outside the study period. The counts here are therefore not
the same number as `ScrapeTarget.occurrence_count`, which counts donors with
any interaction within the study period.

**Where the data comes from.** Three DDM blueprints, each with its backup
variants (the first one that was extracted is used, in this order):

| Interaction | Blueprints                                                                   |
|-------------|------------------------------------------------------------------------------|
| watched     | `watch_history`, `watch_history_txt`, `watch_history_old`, `watch_history_old_api` |
| liked       | `liked_videos`, `liked_videos_txt`, `liked_videos_old`, `liked_videos_old_api`     |
| bookmarked  | `video_bookmarks`, `video_bookmarks_txt`, `video_bookmarks_old`, `video_bookmarks_old_api` |

Every record has a `link` (the video ID is taken from it) and a `date`. A
record whose date cannot be read still counts as an interaction.

**How it is written.** All writes go through
[`ddcs.metadata.donations.service`](../ddcs/metadata/donations/service.py)
(`scan_donated_videos` reads one donation, `record_donated_videos` stores
it):

- **New donations**: `register_donation_metadata` records the donation,
  whether or not the scraper is enabled.
- **Existing donations**: the `record_donated_videos` command goes through
  all stored donations, one at a time:

  ```bash
  python manage.py record_donated_videos [--start 2026-07-01] [--end 2026-09-20] [--dry-run]
  ```

  The same pass rebuilds the scrape queue from the same donations. Options,
  the summary it prints and how to read it are described in
  [8_scraper.md → Queueing](8_scraper.md#1-queueing).

**Counts are added, so the command resets them first.** Recording a donation
raises the counts by one; recording the same donation twice counts it twice.
That happens when the processing of a donation is retried, or when a donation
arrives while the command is running and is then also read by it. The command
therefore sets all counts to zero before it starts, counts from scratch, and
can be repeated at any time to bring the counts back in line. If it is
interrupted, the counts are partial: run it again.

Rows and interaction times are never reset or removed, only moved to a later
time. Priorities, which depend on those, therefore stay as they are while the
command runs. A video no donation backs any more keeps its row with counts of
zero, and narrowing the window later does not clear
`last_interaction_in_window_at`.

Whenever a row is created or an interaction time moves, the video's
`TikTokVideo.updated_at` is moved too (see [`updated_since`](#filters)). A
change of counts alone does not move it, so a recount does not report every
video as changed.

**Test participants.** The command leaves out the participants listed in
`EXCLUDED_PARTICIPANT_IDS`
([`donations/config.py`](../ddcs/metadata/donations/config.py)), matched on
`Participant.external_id`. They are known test cases. Incoming donations are
not checked against the list: new donations always arrive under other IDs.
As the command also rebuilds the scrape queue, the test participants are left
out of the queue's counts as well.


### Data origins

Every base/registry model carries an `added_by` field (a `DataOrigins` value)
recording which subsystem first inserted the row. This is set on creation only —
it is **not** updated when a later subsystem encounters the same object.

| Value          | Set by                                                  | Status        |
|----------------|---------------------------------------------------------|---------------|
| `RESEARCH_API` | `ResearchAPIService`                                    | active        |
| `IMPORT`       | `sync_monitored_items`                                  | active        |
| `DONATION`     | data donation pipeline                                  | not yet wired |
| `SCRAPER`      | `ScraperService` (users, music, hashtags found on scraped video pages) | active |


### Inferred fields

`TikTokVideo.inferred_create_time` is derived from the TikTok ID itself: the
high 32 bits of the ID encode the unix timestamp at which the video was
published (Steel et al., https://doi.org/10.48550/arXiv.2504.13279). The
computation lives in
[`ddcs.metadata.utils.infer_publication_date_from_id`](../ddcs/metadata/utils.py).

**Important:** this field is populated **in the service layer** (see
`ResearchAPIService._sync_video`), not in `TikTokVideo.save()`. As a result,
`bulk_create`, `loaddata`, and direct ORM construction will leave the field
`NULL`. Any new ingestion path (donation pipeline, scraper, importer) must
compute and pass `inferred_create_time` explicitly.


## Prioritised video API

```
GET /metadata/api/v1/tiktok/videos/prioritised/
```

Lists every `TikTokVideo` with a priority and its metadata, for the external
system that classifies the videos and scrapes their media. It is built like
the video list (`/metadata/api/v1/tiktok/videos/`): token authentication,
cursor pagination (`page_size` up to 500, newest registry entry first) and the
same filters. The video list itself is unchanged and still serves Research API
data only. Both are listed in the API docs (`/api/docs/`).

### Priorities

Higher means more important.

| Priority | Videos                                                                                         |
|----------|------------------------------------------------------------------------------------------------|
| 4        | Watched, liked or bookmarked by a donor (at any time) **and** delivered by the Research API    |
| 3        | Watched, liked or bookmarked by a donor within the study period (2026-07-01 to 2026-09-20), no Research API infos |
| 2        | Delivered by the Research API, in no donation                                                  |
| 1        | Everything else, e.g. donated videos with interactions only outside the study period           |

The priority is **not stored**. It is derived for each request from
`DonationVideoInfos` and from whether the video has `APIVideoInfos`
([`ddcs/metadata/priority.py`](../ddcs/metadata/priority.py)), so it is always
current: a priority-3 video becomes priority 4 once the Research API delivers
it, a priority-2 video once a donor who watched, liked or bookmarked it
donates.

Priorities are only as complete as `DonationVideoInfos`. After deploying, run
`python manage.py record_donated_videos` once (see
[Donation Information Models](#donation-information-models-ddcsmetadatadonationsmodels)); until then every video
donated before the deployment counts as not donated.

### Fields

| Field             | Content                                                                                           |
|-------------------|---------------------------------------------------------------------------------------------------|
| `id_tiktok`       | The video ID                                                                                      |
| `priority`        | 4 to 1, see above                                                                                 |
| `metadata_source` | `research_api`, `scraped`, or `null` if the video has no metadata yet                             |
| `last_interaction_at` | Most recent view, like or bookmark of the video in any donation (UTC); `null` if it is in none or the date is unknown |
| metadata          | The fields of the video list: `description`, `create_time`, `created_at`, `region_code`, `duration`, `voice_to_text`, `is_stem_verified`, `video_mention_list`, `effect_list`, `video_label` |
| `user`, `music`, `hashtags`, `keywords` | From the registry, as in the video list                                     |

The metadata fields come from the Research API infos if the video has any,
otherwise from the most recent scrape. `region_code`, `is_stem_verified` and
`video_label` exist only in Research API data and are `null` for scraped
videos. `created_at` is when the served infos were stored here. Videos with
neither source are listed too, with empty metadata, because their media can
still be scraped by ID.

### Filters

All filters of the video list, plus:

| Filter            | Effect                                                                    |
|-------------------|---------------------------------------------------------------------------|
| `priority`        | One or several priorities, comma-separated (`?priority=4,3`)              |
| `metadata_source` | `research_api` or `scraped`                                               |
| `has_metadata`    | `true`: videos with metadata from either source; `false`: those without   |

`updated_since` reports every video whose priority, `last_interaction_at` or
metadata may have changed since then. It is a single condition on
`TikTokVideo.updated_at`, which every such change moves:

| Change                                   | Where `updated_at` is moved                 |
|------------------------------------------|---------------------------------------------|
| A donation shows the video for the first time, or with a later interaction | `donations.service.record_donated_videos` |
| The Research API delivers the video      | `ResearchAPIService._sync_video`            |
| The video is scraped                     | `ScraperService._store`                     |

Any new code that changes what this endpoint serves has to move `updated_at`
as well. This differs from the video list, whose `updated_since` also looks
for newer Research API infos directly; changes from before this endpoint was
deployed are therefore only found there.

The filters inherited from the video list (`create_date*`, `region_codes`,
`has_api_infos`) look at Research API data only; they do not match scraped
videos.

### Performance

Not measured on production data; what follows is how the query is built.

- **One page costs five queries**, whatever the page size: the videos (with
  donation infos, user and music joined), then hashtags, keywords, Research
  API infos and scraped infos for those videos. Cursor pagination makes a
  late page as cheap as the first.
- **`updated_since`** is a range condition on the indexed
  `TikTokVideo.updated_at`.
- **The Research API subqueries behind `create_date*` and `region_codes`**
  only run when one of those filters is used.
- **A `priority` filter is not index-driven.** The database walks the videos
  newest first and keeps those that match, so a page is slow where matches
  are rare, and the last page of a filter scans to the end of the table. If
  that shows in practice, the remedy is to store the priority in an indexed
  column, at the cost of maintaining it wherever Research API infos or
  donation infos are written.

Before the external system starts paging through all videos, run
`EXPLAIN (ANALYZE, BUFFERS)` on the page query for `?priority=4`,
`?priority=2` and `?updated_since=<yesterday>`.

### Things to know

- **Classifications are only pulled back for Research API videos.**
  `sync_tiktok_video_classifications` selects videos by the day their
  Research API infos arrived. Classifications the external system produces
  for scraped videos are not fetched until that task is extended.
- **`last_interaction_at` is a full timestamp.** For a video only one donor
  watched, liked or bookmarked, it is the time that donor did so. The claim
  endpoint for external scrapers already exposes the same kind of value
  (`last_watched_at`).
- **The counts are not served.** `watched_count`, `liked_count` and
  `bookmarked_count` are stored but not part of the response.


## Access Records through the Admin

The four base/registry models have admin entries in
[`ddcs/metadata/admin.py`](../ddcs/metadata/admin.py). Each parent's change page
shows the matching Research API rows as **read-only `TabularInline`s**:

| Parent          | Inlines                               |
|-----------------|---------------------------------------|
| `TikTokVideo`   | `APIVideoInfos`, `APIVideoStatistics` |
| `TikTokUser`    | `APIUserInfos`, `APIUserStatistics`   |
| `TikTokMusic`   | `APIMusicInfos`                       |
| `TikTokHashtag` | `APIHashtagInfos`                     |

The Research API and Scraper models are intentionally **not** registered as standalone
admin entries — they are service-owned and editing historical snapshots through
the admin is not intended.


## Populating the registry

The monitored-item lists are declared in two CSV files committed to the
repository:

- [`ddcs/metadata/fixtures/monitored_users.csv`](../ddcs/metadata/fixtures/monitored_users.csv)
- [`ddcs/metadata/fixtures/monitored_keywords.csv`](../ddcs/metadata/fixtures/monitored_keywords.csv)

Each row is `name` or `name,priority`. Blank lines and `#`-prefixed
lines are ignored — use a `#` prefix to temporarily disable an item
without losing its history. Git history of these files is the audit
trail.

The deployment playbook in ddcs-infra syncs changes in these files
automatically with the DB.

To sync the CSV state manually into the DB, use the `sync_monitored_items`
management command:

```bash
python manage.py sync_monitored_items                   # dry-run: prints plan, writes nothing
python manage.py sync_monitored_items --apply           # commits the plan
python manage.py sync_monitored_items --skip-keywords   # limit to one kind
```

Semantics:

- Names in the file but not in the DB are **created** with
  `monitor_api=True`, `monitoring_priority_api=<from file>` (default `0`),
  `added_by=IMPORT`.
- Names in the DB with `monitor_api=True` but missing from the file
  have `monitor_api` flipped to **`False`** — never hard-deleted, so
  historical `SyncAttempt` rows stay linked.
- Priority changes in the file are applied to already-monitored rows.


## Research API: Monitoring & sync

### Per-object monitoring controls

`TikTokUser`, `Keyword` and `TikTokHashtag` inherit `APIMonitoredMixin`, which adds:

| Field                     | Purpose                                                                                                 |
|---------------------------|---------------------------------------------------------------------------------------------------------|
| `monitor_api`             | Master switch — only objects with `True` are picked up by the sync task.                                |
| `monitoring_priority_api` | Higher values are queried first; lower-priority objects may be dropped when the API quota is exhausted. |

Coverage per `(item, target_date)` is tracked in `SyncAttempt`. 
"Was this item synced for date D?" is answered by `SyncAttempt.filter(<item>, target_date=D,
status=SUCCESS).exists()`.

> **Note:**
> Hashtags have the monitoring controls, because the initial version of the application
> monitored by hashtag. This has since been changed to be monitored explicitly by
> _Keyword_, because the ResearchAPI is queried by looking for the keyword in the 
> description, making monitoring by Hashtag misleading.

### The sync tasks

[`research_api/tasks.py`](../ddcs/metadata/research_api/tasks.py)
defines three Celery tasks. See
[7_research_api_sync.md](7_research_api_sync.md) for the full strategy
and manual-trigger runbook; this section is a summary.

- **`daily_sync_users`** (02:00) and **`daily_sync_keywords`** (03:00)
  each pull one day of data — `today − 4 days` by default. They
  process every monitored item that doesn't yet have a `SUCCESS`
  `SyncAttempt` for that date, ordered by
  `-monitoring_priority_api`. Batches (users: 200, keywords: 50) are
  queried against the Research API; each batch writes one
  `SyncAttempt` per (item, date) with the outcome. Retries fire at
  the Celery task level (3 attempts over ~7 min) with halving
  batch size on partial failure and preserved batch size on rate
  limit.

- **`backfill_missing_syncs`** (10:00, 16:00) walks all target dates
  from `settings.API_MONITORING_START_DATE` up to `today − 4 days`,
  newest first. Users are processed before keywords. It uses a Redis
  lock (so overlapping runs are prevented and can't double-spend quota), 
  and bails early on rate-limit rather than iterating into the same limit again.

**Query window:** the daily tasks target `today − 4 days` because
TikTok's publication data becomes stable around then. A failed daily
run leaves gap rows that the backfill task closes on the next
scheduled invocation.

### Schedule

The bootstrap beat schedule lives in
[`config/settings/base.py`](../config/settings/base.py) under
`CELERY_BEAT_SCHEDULE`. Beat uses `DatabaseScheduler`
(`django_celery_beat`) — the settings dict only populates the DB on
first start; after that the DB rows are authoritative and can be
edited via the Django admin under **Periodic Tasks**.

**IMPORTANT:** if you edit the bootstrap dict after beat has already
run once, your changes are ignored until you delete the existing
`PeriodicTask` rows from the DB. Adjust the schedule in the admin
instead. See
[7_research_api_sync.md](7_research_api_sync.md#manually-triggering-a-task)
for step-by-step guidance.
