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
| `IMPORT`       | `sync_monitored_items`                                  | active        |
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
