# Documentation of the Data Pipeline

This document describes how a participant's donated TikTok data flows through
the system: from the moment they hit "submit" to the moment their personal
report renders. It glues together the per-app documentation
([datadonation](3_datadonation.md), [metadata](4_metadata.md),
[reports](5_reports.md)) into one end-to-end picture.

## High-level flow

```
┌────────────────┐    ZIP/portability   ┌────────────────────┐    decrypt   ┌──────────────────┐
│ Participant    │ ───────────────────▶ │ ddcs.datadonation  │ ───────────▶ │ TikTokUserData   │
└────────────────┘                      └────────────────────┘              └──────────────────┘
                                                                                     │
                                                  ┌──────────────────────────────────┴───┐
                                                  ▼                                      ▼
                                       ┌──────────────────────┐               ┌──────────────────────────┐
                                       │ ddcs.metadata        │               │ ddcs.reports             │
                                       │  register_donation_… │               │  generate_report_…       │
                                       │ → TikTokVideo/User   │               │ → ParticipantReportStats │
                                       └──────────────────────┘               └──────────────────────────┘
                                                                                     │
                                                                                     ▼
                                                                          ┌──────────────────────────┐
                                                                          │ Participant views report │
                                                                          └──────────────────────────┘
```

In parallel, the **Research API sync** continuously enriches `TikTokVideo`,
`TikTokUser`, `TikTokHashtag` rows with the data the report depends on
(account → party assignment via the CSV, hashtag monitoring, video creation
times, etc.).

## Step-by-step

### 1. Donation arrives

Path: [`ddcs.datadonation.views.DonationViewDDM`](../ddcs/datadonation/views.py)
(or the portability OAuth handoff).

- DDM stores the donation encrypted, one row per blueprint
  (`watch_history`, `followed_accounts`, `liked_videos`).
- After the upload, `DonationViewDDM.process_uploads()` calls
  `post_process_donation(participant)` — the single entry point for everything
  downstream.

### 2. `post_process_donation` runs the pipeline

Defined in [`ddcs.datadonation.services`](../ddcs/datadonation/services.py).
The pipeline today is **synchronous** (TODO: move to Celery once we measure
typical runtime on real data):

```python
def post_process_donation(participant: Participant):
    user_data = get_user_data(participant)
    register_donation_metadata(user_data)
    generate_report_statistics(participant, user_data)
```

Three stages, in order.

### 3. `get_user_data` — decrypt + normalise

Same module. Fetches the three encrypted DDM `DataDonation` rows for this
participant, decrypts them with the project's salt/secret, normalises each
record (lowercases keys, parses dates with `_parse_date`, attaches a parsed
`video_id` from the link), and returns a `TikTokUserData` dataclass with three
optional lists: `watch_history`, `followed_accounts`, `liked_videos`.

Anything malformed — un-parseable dates, missing video IDs — is preserved
where harmless and dropped where it would otherwise break downstream
arithmetic. A summary count of un-parseable dates is logged once per donation.

### 4. `register_donation_metadata` — populate the registry

Lives in [`ddcs.metadata.services`](../ddcs/metadata/services.py). For every
video and user discovered in the donation, an entry is upserted into the
`TikTokVideo` / `TikTokUser` registry with `added_by=DataOrigins.DONATION`.

This stage is **not** the source of party/hashtag classification — it only
ensures the registry knows the IDs exist. Enrichment (the actual Research API
fields, monitored-hashtag flags) is done by the periodic Research API sync,
independently of any donation. See
[4_metadata.md](4_metadata.md#research-api-monitoring--sync).

### 5. `generate_report_statistics` — compute + persist the report

Lives in [`ddcs.reports.services`](../ddcs/reports/services.py). Calls
`compute_report_statistics(user_data)` and stores the resulting
`ReportStatistics` `TypedDict` as a `ParticipantReportStatistics` row.

The compute step:

- Loads the party-account CSV (cached).
- Pulls **two** sets of political videos from the metadata DB:
  - `TikTokVideo` rows whose `user.name` is in the CSV → party-account videos.
  - `TikTokVideo` rows with at least one `TikTokHashtag` where
    `monitor_api=True`, excluding party-account users → non-party political
    videos.
- Intersects both with the participant's donated `seen_video_ids` and
  `liked_video_ids`.
- Builds per-party counts, daily counts, top-N videos, and party / non-party
  hashtag buckets.
- Returns the `ReportStatistics` dict; the caller `**`-spreads it into the
  `ParticipantReportStatistics` model.

For details on the dual definition of "political" and how to extend this
layer, see [5_reports.md](5_reports.md#extending-the-report).

### 6. Participant views the report

Path: [`ddcs.reports.views.GetReportView`](../ddcs/reports/views.py). The page
shell at `/report/<participant_id>/` loads, HTMX fetches
`/report/get/<participant_id>/`, which:

- Resolves the participant by `external_id`.
- Loads the latest `ParticipantReportStatistics` row, or computes one on the
  fly if (somehow) none exists yet.
- Builds the plot HTML, the wordcloud SVGs, and the top-videos table, and
  renders them into the body template.

## Out-of-band: the metadata enrichment loop

Independent of any donation:

- Celery beat runs the Research API tasks
  ([`query_videos_by_user`, `query_videos_by_hashtag`](../ddcs/metadata/research_api/tasks.py))
  on schedule. They pull new videos for monitored users and hashtags.
- A management command imports newly approved users and hashtags into the
  monitored set (see [4_metadata.md](4_metadata.md#populating-the-registry)).

The reports app reads from the registry but does not write to it; the
metadata app writes to the registry but does not read from donations beyond
what `register_donation_metadata` puts there.

## Failure handling

A few realistic failure modes and what happens today:

| Stage                              | Failure                                      | Outcome                                                                                                                                                                 |
|------------------------------------|----------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| ZIP upload                         | Malformed export                             | DDM rejects the upload; participant sees an error and can retry.                                                                                                        |
| `get_user_data`                    | Un-parseable date(s)                         | Skipped; summary logged. Other records still processed.                                                                                                                 |
| `register_donation_metadata`       | Race on duplicate `TikTokVideo`/`TikTokUser` | Handled by `update_or_create`/upsert pattern.                                                                                                                           |
| Research API sync                  | Day skipped (task fails or beat down)        | The participant's report computed during the gap may underrepresent political content from that window. See known TODO in [4_metadata.md](4_metadata.md#the-sync-task). |
| `generate_report_statistics`       | Empty metadata DB                            | Statistics are valid but show 0 political exposure. Participant still sees a (boring) report.                                                                           |
| `GetReportView`                    | Unknown `participant_id`                     | `Http404`. (No "specific error view" yet — TODO in the view.)                                                                                                           |

## Where to make changes

- **Touch what gets stored in the donation.** Adjust DDM blueprints in the
  DDM admin, and the constants in
  [`ddcs.datadonation.config`](../ddcs/datadonation/config.py).
- **Touch how records are cleaned.** Edit `_clean_record` /
  `_clean_donated_data` in
  [`ddcs.datadonation.services`](../ddcs/datadonation/services.py).
- **Touch what counts as political.** Edit the CSV or
  `compute_report_statistics()` in
  [`ddcs.reports.services`](../ddcs/reports/services.py).
- **Touch what the report shows.** See
  [5_reports.md → Extending the report](5_reports.md#extending-the-report).
- **Touch how/when metadata is enriched.** See
  [4_metadata.md → Monitoring & sync](4_metadata.md#research-api-monitoring--sync).
