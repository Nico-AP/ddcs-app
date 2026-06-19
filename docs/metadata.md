# Documentation of TikTok Metadata Enrichment

TikTok metadata enrichment is handled by the `ddcs.metadata` app.

We use two sources to enrich metadata:

1. TikTok's Research API
2. Information scraped from TikTok


## How metadata is stored

To honor that information may come from different sources and make it retraceable,
we use a database design that distinguishes between *Base/Registry Models*,
models capturing *Research API information* and models capturing *scraped information*.

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

- `VideoInfosScraped` → `TikTokVideo`
- `UserInfosScraped` → `TikTokUser`

**Status:** the scraper app has not yet been implemented; everything that exists
is placeholder code.


### Data origins

Every base/registry model carries an `added_by` field (a `DataOrigins` value)
recording which subsystem first inserted the row. This is set on creation only —
it is **not** updated when a later subsystem encounters the same object.

| Value          | Set by                                                  | Status        |
|----------------|---------------------------------------------------------|---------------|
| `RESEARCH_API` | `ResearchAPIService`                                    | active        |
| `IMPORT`       | `import_users_to_monitor`, `import_hashtags_to_monitor` | active        |
| `DONATION`     | data donation pipeline                                  | not yet wired |
| `SCRAPER`      | scraper service                                         | not yet wired |


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


## Populating the registry

Initial users and hashtags to monitor are loaded from newline-delimited text
files via management commands:

```bash
python manage.py import_users_to_monitor    [--file PATH] [--priority N]
python manage.py import_hashtags_to_monitor [--file PATH] [--priority N]
```

- Default input paths are `ddcs/metadata/fixtures/tiktok_users_to_monitor.txt`
  and `ddcs/metadata/fixtures/hashtags_to_monitor.txt`.
- The file format is one name per line. Blank lines and (for the users file)
  `#`-prefixed comment lines are ignored. Hashtag lines may carry a leading `#`,
  which is stripped.
- For each name, the command calls `update_or_create`:
  - **New rows** are created with `monitor_api=True`,
    `monitoring_priority_api=<--priority>`, `added_by=IMPORT`.
  - **Existing rows** have `monitor_api=True` re-asserted, but `priority` and
    `added_by` are **preserved**. This means re-running an import will not
    bump priorities — change them in the admin or by a targeted migration.
- The command reports `created` vs `updated` counts on stdout.


## Monitoring & sync

### Per-object monitoring controls

`TikTokUser` and `TikTokHashtag` inherit `APIMonitoredMixin`, which adds:

| Field                     | Purpose                                                                                                 |
|---------------------------|---------------------------------------------------------------------------------------------------------|
| `monitor_api`             | Master switch — only objects with `True` are picked up by the sync task.                                |
| `monitoring_priority_api` | Higher values are queried first; lower-priority objects may be dropped when the API quota is exhausted. |
| `api_last_monitored_at`   | Timestamp of the last successful sync; used to skip objects already synced today.                       |

### The sync task

[`research_api/tasks.py`](../ddcs/metadata/research_api/tasks.py) defines
`query_videos_by_user` and `query_videos_by_hashtag` the Celery task that pulls new videos for monitored users/hashtags:

1. Selects `TikTokUser`/`TikTokHashtag` rows where `monitor_api=True` and
   `api_last_monitored_at__date != today`, ordered by
   `(-monitoring_priority_api, api_last_monitored_at)`.
2. Batches them (default 50 per batch) and calls
   `ResearchAPIService.get_user_videos` per batch.
3. Updates `api_last_monitored_at` for each user/hashtag once their batch completes.
4. Logs sync stats (`users_created`, `videos_created`, `hashtags_created`,
   `music_created`) at the end.

**Query window:** each run asks for videos posted 4 days before the day it runs. 
If the task fails on one day, content posted during the gap will be missed.

=> TODO: Implement a mitigation strategy.

### Schedule

The Celery beat schedule is configured in [`config/celery.py`](../config/celery.py).
`query_videos_by_user` and `query_videos_by_hashtag` will be automatically added 
to scheduled tasks. IMPORTANT: Changes to this setting will not take effect on
existing systems, that already have the task schedule populated (i.e., existing 
tasks take precedent). If changes are made to the default schedule, these must
be manually added to running systems.


## Admin

All four base/registry models have admin entries in
[`ddcs/metadata/admin.py`](../ddcs/metadata/admin.py). Each parent's change page
shows the matching Research API rows as **read-only `TabularInline`s**:

| Parent          | Inlines                               |
|-----------------|---------------------------------------|
| `TikTokVideo`   | `APIVideoInfos`, `APIVideoStatistics` |
| `TikTokUser`    | `APIUserInfos`, `APIUserStatistics`   |
| `TikTokMusic`   | `APIMusicInfos`                       |
| `TikTokHashtag` | `APIHashtagInfos`                     |

The Research API models are intentionally **not** registered as standalone
admin entries — they are service-owned and editing historical snapshots through
the admin is not intended.
