# Research API sync

This section described how the Research API pulls TikTok video metadata 
for monitored users and keywords, and how to trigger / diagnose it manually.

## Goal

Have a **complete, per-day sync** of every monitored user and keyword.
Concretely: for every `(monitored_item, target_date)` pair from the
`API_MONITORING_START_DATE` up to `today − 4 days`, we want at least one
successful `SyncAttempt` row.

TikTok's Research API needs the ~4-day lag because the information in 
their database is assumed to become stable around then; syncing more 
recent days risks getting an incomplete picture.

Generally, user coverage is prioritized over keyword coverage. 
The coverage is currently set to start June 1 (`API_MONITORING_START_DATE`).

## Two-tier task model

The whole system consists of two scheduled tasks and one shared coverage table.

### Daily sync task — fresh data, once a day

Two tasks, one per kind of monitored item:

| Task                       | Runs at    | Target date default   |
|----------------------------|------------|-----------------------|
| `daily_sync_users`         | 02:00      | `today − 4 days`      |
| `daily_sync_keywords`      | 03:00      | `today − 4 days`      |

Each run:

1. Loads every monitored item (`monitor_api=True`) that does **not** yet
   have a `SyncAttempt.status=SUCCESS` row for the target date.
2. Orders by `monitoring_priority_api` descending — high-priority items
   get quota first.
3. Batches (users: 200 per batch, keywords: 50 per batch), queries the
   Research API, and writes one `SyncAttempt` row per (item, date) with
   the outcome (`success`, `rate_limited`, `timeout`, `api_error`).
4. On partial failure or soft-time-limit, Celery-level retries fire
   with the batch size halved (poison-pill isolation - especially relevant 
   for users). On rate limit, retries preserve the batch size 
   (batch size doesn't matter in these cases).
5. Retry window is tight — 3 attempts over ~7 minutes. Anything that
   doesn't succeed there falls to the backfill task.

### Backfill task — close historical gaps

`backfill_missing_syncs`, scheduled at **10:00** and **16:00**.

1. Iterates `(kind, target_date)` pairs in priority order:
   - **All users first, then keywords** — user coverage is more important.
   - **Newest date first**, walking back to `API_MONITORING_START_DATE`.
2. For each pair, gathers every monitored item (`monitor_api=True`)
   that does **not** yet have a `SyncAttempt.status=SUCCESS` row for the target date.
3. Runs until one of:
   - **No gaps remain** — happy path.
   - **Rate limit trips** — stops cleanly; the next scheduled run
     resumes.
   - **Soft time limit (110 min)** — Celery interrupts; next run resumes.
4. Uses a Redis lock so two backfills can't ever double-spend quota.

There is no per-run page/quota budget: after the daily sync has run,
whatever quota is left in the day is used by the backfill task.

### Coverage tracking

Every attempt against every (item, date) writes a `SyncAttempt` row.
Multiple rows may exist per pair — every retry appends, never
overwrites — so failure frequency is auditable. An item counts as
"synced for that date" if any row has `status=SUCCESS`.

`status=SUCCESS` is set when we received a valid result from the 
Research API (i.e., no error) - it does not mean that any videos were
actually retrieved.

The companion table `ResearchAPIQueryTracker` records one row per
Celery-task invocation (start/end time, parameters, result counts,
overall status). Each `SyncAttempt.tracker` FK points back to the
tracker that produced it.

## Manually triggering a task

Two supported paths: **django-celery-beat admin** (recommended for
one-shot runs and beat-schedule changes) and **Django shell** (fast
ad-hoc for debugging; not recommended on the server).

### Path A: django-celery-beat admin

The beat scheduler is `django_celery_beat.schedulers.DatabaseScheduler`,
so all schedule entries live in the DB and can be managed from the
Django admin under **Periodic Tasks**.

**One-off run of an existing scheduled task:**

1. Open the admin → **Periodic Tasks**.
2. Tick the checkbox next to the entry (e.g.
   `researchapi-daily-sync-users`).
3. From the actions dropdown at the top, choose **Run selected tasks**
   → **Go**. The task fires immediately as a Celery job; the schedule
   is unaffected.

**Create a fresh run with custom arguments:**

1. **Periodic Tasks** → **Add Periodic Task**.
2. Fill in:
   - **Name**: e.g. `manual-backfill-2026-06-28`
   - **Task (registered)**: pick from the dropdown
     (`ddcs.metadata.research_api.tasks.daily_sync_users`, etc.).
   - **Enabled**: leave unchecked if this is a one-shot — you'll trigger
     it manually rather than let a schedule fire it.
   - **Schedule**: pick any (interval or crontab) — required by the
     form, but a disabled entry never fires on schedule.
   - **Keyword arguments** (JSON, see next section for what each task
     accepts): e.g.
     ```json
     {"target_date": "2026-06-28", "batch_size": 10}
     ```
   - Leave **Arguments** empty — all tasks use kwargs only.
3. Save.
4. Tick the new entry and use **Run selected tasks** to fire it.
5. Delete the entry when you're done (or leave `Enabled=false` for
   future reuse).

**Change the beat schedule** (e.g. move `daily_sync_users` to 04:00):

1. Open the existing entry (`researchapi-daily-sync-users`).
2. Edit **Crontab** or attach a different **Interval** schedule.
3. Save. `celery-beat` picks up the change on its next poll (~a
   minute) — no restart required.

**Note:** the `CELERY_BEAT_SCHEDULE` dict in
[`config/settings/base.py`](../config/settings/base.py) is only used
to *bootstrap* the DB the very first time beat starts. Once entries
exist in the DB they are authoritative; edits to the dict are ignored
unless you delete the DB entries.

### Path B: Django shell

Useful for quickly running a task inline (synchronously, no worker
required) — good for debugging.

```bash
python manage.py shell
```

```python
from ddcs.metadata.research_api.tasks import daily_sync_users
# Sync a specific historical day with a smaller batch:
daily_sync_users.apply(kwargs={"target_date": "2026-06-28", "batch_size": 5})
```

`.apply(...)` runs in-process. `.delay(...)` / `.apply_async(...)`
enqueue for a worker.

## Task parameters reference

### `daily_sync_users`, `daily_sync_keywords`

| kwarg          | Type          | Default              | Meaning                                             |
|----------------|---------------|----------------------|-----------------------------------------------------|
| `target_date`  | `str \| None` | `today − 4 days`     | ISO date (`"YYYY-MM-DD"`) to sync.                  |
| `batch_size`   | `int`         | 200 (users), 50 (kw) | Items per API request. Halved on retry.             |
| `max_retries`  | `int \| None` | `3` (from decorator) | Override the Celery-level retry cap for this run.   |
| `force_resync` | `bool`        | `False`              | If True, re-query items that already have a SUCCESS SyncAttempt for `target_date`. |

The `max_retries` override propagates: it's forwarded into each retry's
kwargs, so the whole chain uses the overridden value. Useful when you
want the halving retry to bottom out at `batch_size=1`.

`force_resync=True` applies only to the initial run. Retries fall back
to the normal filter (items without a SUCCESS attempt), so subsequent
attempts only touch items that failed in the initial forced run — you
don't pay quota to re-query items that succeeded on the forced pass.
Use when you suspect a previous "successful" sync returned an
incomplete set (e.g., after an API incident) and want fresh data on
top.

Example admin **Keyword arguments** JSON:

```json
{"target_date": "2026-06-28"}
```
```json
{"target_date": "2026-06-28", "batch_size": 5}
```
```json
{"target_date": "2026-06-28", "max_retries": 4}
```
```json
{"target_date": "2026-06-28", "force_resync": true}
```

### `backfill_missing_syncs`

No arguments — it always scans from `API_MONITORING_START_DATE` up to
`today − 4 days` and processes what it finds. If you want to focus a
backfill on a specific date, use `daily_sync_users` /
`daily_sync_keywords` with an explicit `target_date` instead.

## Common diagnostic queries

### "Which items are missing coverage for date D?"

```python
from datetime import date
from django.db.models import Exists, OuterRef
from ddcs.metadata.models import SyncAttempt, TikTokUser

D = date(2026, 6, 28)
success = SyncAttempt.objects.filter(
    user=OuterRef("pk"), target_date=D, status="success",
)
TikTokUser.objects.filter(monitor_api=True).annotate(
    ok=Exists(success)
).filter(ok=False).values_list("name", flat=True)
```

Swap `TikTokUser`/`user` for `TikTokHashtag`/`hashtag` for keywords.

### "What error patterns are we seeing on date D?"

```python
from django.db.models import Count
from ddcs.metadata.models import SyncAttempt

(SyncAttempt.objects
 .filter(target_date=D)
 .exclude(status="success")
 .values("error_details__type", "error_details__message")
 .annotate(n=Count("id"))
 .order_by("-n")[:20])
```

### "How much quota did the last run consume?"

To get an estimate of the used quota, look at the latest `ResearchAPIQueryTracker` 
row in the admin — the `query_result` JSON has `pages_retrieved`, 
which is the count of pages successfully returned and each page
equals one billed quota point (assuming
TikTok bills successful responses). Retries of failed calls consume
additional quota points, so in the case of partial failures you
also need to add these to the consumed total.

### Admin browsing

The **Sync attempts** admin (top-level) has:

- **Outcome** filter (Success / Any failure) — the fastest way to
  isolate problems.
- **Status** filter — drill down to specific failure kinds.
- **Target kind** filter — user vs keyword.
- **Date hierarchy** on `target_date` — Year → Month → Day.
- Free-text search on user/hashtag name.

## Configuration knobs

Settings that shape sync behavior (all in
[`config/settings/base.py`](../config/settings/base.py)):

| Setting                                              | Default      | Effect                                                               |
|------------------------------------------------------|--------------|----------------------------------------------------------------------|
| `API_MONITORING_START_DATE`                          | `2026-05-01` | Oldest date the backfill task will consider.                         |
| `TIKTOK_RESEARCH_API_CLIENT_MAX_RETRIES`             | `1`          | Client-level retries per HTTP call. Higher values waste quota.       |
| `CELERY_BROKER_TRANSPORT_OPTIONS.visibility_timeout` | `7200`       | Redis broker redelivery safety net — must be ≥ 2× task `time_limit`. |

## Managing the monitored list

Users and keywords are declared in CSV files:

- [`ddcs/metadata/fixtures/monitored_users.csv`](../ddcs/metadata/fixtures/monitored_users.csv)
- [`ddcs/metadata/fixtures/monitored_keywords.csv`](../ddcs/metadata/fixtures/monitored_keywords.csv)

Format: `name` or `name,priority` per line. Lines starting with `#`
are ignored (use this to temporarily disable a monitored item without
losing history).

Sync the CSV state into the DB via:

```bash
# Dry run — shows the plan, writes nothing.
python manage.py sync_monitored_items

# Actually apply.
python manage.py sync_monitored_items --apply
```

Removals set `monitor_api=False` (never hard-delete), so historical
`SyncAttempt` rows stay linked. The Ansible deploy runs `--apply`
automatically after each git pull.

See also section "Populating the registry" in [4_metadata.md](4_metadata.md).


## Changelog

- __09.07.2026:__ TikTok changed API response structure. `hashtag_name` was removed 
  from dictionaries contained in `hashtag_info_list`. To account for this,
  `ResearchAPIService._sync_hashtag` was replaced with `ResearchAPIService._sync_hashtag_name`
  and the information contained in the API response's `hashtag_names` is now used
  to identify video hashtags (instead of `hashtag_info_list.0.hashtag_name`. 
  Hashtag IDs and descriptions are no longer synced, because the current 
  response structure does not explicitly and unambiguously map its `hashtag_names`
  to its `hashtag_info_list` (the mapping would presumably based on the position
  in the lists, but this assumption is undocumented on TikTok's side).
  As a consequence `APIHashtagInfos` is no longer populated (`f101ea8`).
