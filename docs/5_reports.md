# Documentation of the Reports

The `ddcs.reports` app generates the **personalized report** each participant
sees at the end of the donation flow. The report shows them
what political TikTok content they have been exposed to: how many videos they
watched per party, how that distribution evolved over time, the most-watched
political accounts in their feed, and hashtag wordclouds.

The report is computed once per participant from their donated data and a
project-wide registry of **political content** (party accounts from a CSV;
non-party political accounts identified by their use of monitored hashtags).
The computed statistics are persisted as `ParticipantReportStatistics` and the
HTML is assembled at request time via HTMX from those stats.

A general, not participant-specific report will be added later.

## What's in here

| File                                                                               | Purpose                                                                                                                                                               |
|------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`views.py`](../ddcs/reports/views.py)                                             | The HTMX endpoints: `MainReportView` (page shell), `GetReportView` (computes/loads + renders the body), `GetSyntheticReportView` (demo using fake data).              |
| [`services.py`](../ddcs/reports/services.py)                                       | Pure business logic — `compute_report_statistics()` and `generate_report_statistics()`. No UI concerns.                                                               |
| [`models.py`](../ddcs/reports/models.py)                                           | `ParticipantReportStatistics`: one row per generated report; all interesting fields are `JSONField`s.                                                                 |
| [`types.py`](../ddcs/reports/types.py)                                             | `TypedDict`s for the structured JSON: `PartyCountRecord`, `DailyPartyCountRecord`, `TopVideoRecord`, and `ReportStatistics` (the full shape returned by `compute_…`). |
| [`plots.py`](../ddcs/reports/plots.py)                                             | Plotly figure builders (treemap, stacked-area). Each returns `{"html": <str>}` or `{"html": None}`.                                                                   |
| [`wordclouds.py`](../ddcs/reports/wordclouds.py)                                   | SVG wordcloud builder. Single public entry `get_wordcloud(hashtags, *, is_party_account=…)`.                                                                          |
| [`utils.py`](../ddcs/reports/utils.py)                                             | `load_account_party_mapping()` — cached CSV loader.                                                                                                                   |
| [`config.py`](../ddcs/reports/config.py)                                           | Constants: party order, exclude-list of generic hashtags, report cutoff date, top-N counts, static path for the Plotly JS bundle.                                     |
| [`factories.py`](../ddcs/reports/factories.py)                                     | `get_synthetic_report_statistics()` — random-but-shaped data for the synthetic preview view.                                                                          |
| [`data/account_party_mapping.csv`](../ddcs/reports/data/account_party_mapping.csv) | Project-managed list of `username,partei` pairs. Single source of truth for "this account belongs to that party".                                                     |
| [`templates/reports/`](../ddcs/reports/templates/reports)                          | `base.html` (page shell), `report_body.html` (HTMX target), `partials/` (top-videos table, intro text, etc.).                                                         |

## Endpoints

| URL                                | View                       | What it returns                                              |
|------------------------------------|----------------------------|--------------------------------------------------------------|
| `report/<participant_id>/`         | `MainReportView`           | Page shell with a loading state; HTMX-fetches the body.      |
| `report/get/<participant_id>/`     | `GetReportView`            | Rendered report body (intro + plots + table + wordclouds).   |
| `report/get/synthetic/`            | `GetSyntheticReportView`   | Same body, but driven by `factories.get_synthetic_report_statistics`. |

`participant_id` is the DDM `Participant.external_id` — a random 24-character
token issued at participation start. It acts as a capability: anyone who has
the token can view the report (see the module docstring in `views.py`). No
session/auth check is layered on top.

## Configuration

There are no environment variables that belong to this app. Configuration is
all in [`config.py`](../ddcs/reports/config.py):

| Constant                          | Meaning                                                                                         |
|-----------------------------------|-------------------------------------------------------------------------------------------------|
| `ACCOUNT_PARTY_MAPPING_CSV_PATH`  | Path to the party-account CSV.                                                                  |
| `PLOTLY_JS_STATIC_PATH`           | Relative static path of the Plotly JS bundle; resolved via `static()` at request time.          |
| `REPORT_FIRST_DATE_TO_INCLUDE`    | Cutoff: watch-history entries before this date are dropped.                                     |
| `NO_PARTY_KEY`                    | Bucket label for non-party-affiliated political (and unrelated) content.                        |
| `PARTIES_ORDER`                   | Display order of parties in the treemap / stacked area; unknown parties go last alphabetically. |
| `N_TOP_VIDEOS`                    | How many videos to include in the "top videos" table.                                           |
| `HASHTAGS_TO_EXCLUDE`             | Generic hashtags filtered out of the wordclouds (`fyp`, `viral`, etc.).                         |

## Setup

The app needs three things to produce useful output:

1. **The party-account CSV** ([`data/account_party_mapping.csv`](../ddcs/reports/data/account_party_mapping.csv))
   must contain `partei,username` rows for every party account you want to
   recognise. This list is committed to the repo and treated as authoritative
   — the loader is cached via `lru_cache`. If you edit the CSV in a running
   process call `load_account_party_mapping.cache_clear()` (or restart <- the usual way).

2. **Monitored hashtags** must be imported into `TikTokHashtag` so that
   `monitor_api=True` is set on the rows we want to use as "political keyword"
   signals. See [4_metadata.md](4_metadata.md#populating-the-registry).

3. **Metadata for political content must exist in the database** before a
   participant's report is generated. The Research API sync task in
   [`ddcs.metadata.research_api`](../ddcs/metadata/research_api) keeps the
   registry of party-account videos and hashtag-bearing videos up to date.

A report computed against an empty metadata DB will be technically valid (the
participant just sees zero political exposure) but uninteresting.

The Plotly JS bundle is served as a static asset from
`ddcs/reports/static/reports/js/plotly-3.6.0.min.js`. Make sure
`python manage.py collectstatic` includes it in deployments.

## How a report is produced

1. Participant lands on `report/<external_id>/`. `MainReportView` renders the
   page shell with a loading icon and HTMX-fetches the body.
2. `GetReportView.setup()` resolves the `Participant` and pulls (or computes)
   `ParticipantReportStatistics` for them.
3. If no row exists yet, `compute_report_statistics(data)` runs:
   - Fetches party-account videos and non-party political videos
     (hashtag-based) from the metadata DB.
   - Intersects them with the participant's `seen_video_ids` and
     `liked_video_ids` to produce the political subsets.
   - Computes per-party counts, daily counts, top videos, hashtag buckets.
   - Returns a `ReportStatistics` `TypedDict`. The view persists it via
     `generate_report_statistics()` (writes a new row).
4. `GetReportView.get_context_data()` builds plot HTML / wordcloud SVG from
   the persisted stats and renders `report_body.html`.

For the broader pipeline (donation → metadata → report) see
[6_data_pipeline.md](6_data_pipeline.md).

---

## Extending the report

This section is the bit you came for if you're adding a new statistic or a
new visualisation. The architecture is layered, so an addition usually touches
multiple files in a predictable order.

### Mental model: the four layers

```
┌─────────────────────────────────────────────────────────────────┐
│ template      report_body.html (+ partials/)                    │  ← rendering
├─────────────────────────────────────────────────────────────────┤
│ view layer    GetReportView.get_context_data() / plots / clouds │  ← shaping for templates
├─────────────────────────────────────────────────────────────────┤
│ persistence   ParticipantReportStatistics (JSONField columns)   │  ← serialised stats
├─────────────────────────────────────────────────────────────────┤
│ compute layer compute_report_statistics() (+ helpers)           │  ← business logic
└─────────────────────────────────────────────────────────────────┘
```

A new statistic must round-trip cleanly through all four. A new visualisation
of an existing statistic only touches the top two.

### Recipe A — Add a new **statistic** (new data field + new visualisation)

Use this when you want to compute something new (e.g. "share of weekend
watching") and show it.

1. **Type the field.** If the statistic has structure, add a `TypedDict` in
   [`types.py`](../ddcs/reports/types.py) (mirror the existing
   `PartyCountRecord` style). Then add an entry to `ReportStatistics` so the
   contract with the model is explicit.

2. **Persist it.** Add the field to
   [`models.ParticipantReportStatistics`](../ddcs/reports/models.py) as a
   `JSONField` (or a different appropriate Django field). Generate
   and commit the migration:
   ```bash
   python manage.py makemigrations ddcs_reports
   ```

3. **Compute it.** Add a private helper in
   [`services.py`](../ddcs/reports/services.py) (`_compute_share_of_weekend(...)`
   etc.) that takes whatever it needs from `TikTokUserData` and/or the
   already-built helper outputs (`video_party_map`, `seen_pol_video_ids`, …).
   Call it from `compute_report_statistics()` and add the result to the
   returned dict under the same key as the model field.

4. **Synthetic mirror.** Add a `_synthetic_*()` helper in
   [`factories.py`](../ddcs/reports/factories.py) and wire it into
   `get_synthetic_report_statistics()` so the synthetic preview view stays
   useful when developing the new section.

5. **Build the view-side artefact.**
   - For a Plotly chart: add a `get_<name>_plot_user(records)` function in
     [`plots.py`](../ddcs/reports/plots.py). Follow the existing pattern:
     guard `if not relevant_data: return {"html": None}`, build the figure,
     return `{"html": _create_plot_html(fig, config=...)}`.
   - For a wordcloud: in most cases you can call the existing
     `get_wordcloud(hashtags, is_party_account=...)`. Add a new public
     function only if you need a different colour scheme or a different
     filter pipeline.
   - For a table/list/number: shape it inside the view (a new method on
     `GetReportView`) and put it in `context`.

6. **Wire it into the view.** Add a key to `GetReportView.get_context_data()`
   and read from `self.statistics.<new_field>`.

7. **Render it.** Either inline a block in
   [`templates/reports/report_body.html`](../ddcs/reports/templates/reports/report_body.html)
   or, for anything non-trivial, add a partial under
   [`templates/reports/partials/`](../ddcs/reports/templates/reports/partials)
   and `{% include %}` it.

8. **Tests.** Mirror the existing structure in `ddcs/reports/tests.py`:
   one test class for the compute helper(s), one for the synthetic factory,
   one for the plot/wordcloud branch (empty → `None`, populated → contains
   expected markup), and an integration assertion in
   `ComputeReportStatisticsTests` for the end-to-end shape.

### Recipe B — Add a new **visualisation** of an existing statistic

Only the top two layers are touched.

1. Add a builder in [`plots.py`](../ddcs/reports/plots.py) or
   [`wordclouds.py`](../ddcs/reports/wordclouds.py).
2. Call it from `GetReportView.get_context_data()`; add a context key.
3. Add the markup to the template.
4. Test the builder's empty-vs-populated branches.

No migration, no factory change, no compute-layer change.

### Recipe C — Change the **definition** of "political video"

If you change what counts as political (e.g. add a third bucket, change the
party-vs-non-party criteria), the surgery happens in
`compute_report_statistics()` and `_build_political_video_metadata()` in
[`services.py`](../ddcs/reports/services.py). Today:

- Party-account videos come from `TikTokVideo.user.name ∈ CSV usernames`.
- Non-party political videos come from
  `TikTokVideo.hashtags__monitor_api=True` excluding party-account users.

Both feed `_build_political_video_metadata` which assigns each video either a
party label (from CSV) or `NO_PARTY_KEY`. Downstream code uses `NO_PARTY_KEY`
as the signal to route hashtags to the **non-party wordcloud** rather than
the **party-aligned wordcloud**, and the treemap/temporal plots filter
`NO_PARTY_KEY` out by default.

When in doubt, the integration tests in
`ComputeReportStatisticsTests` (in `ddcs/reports/tests.py`) are the clearest
specification of the current semantics: a small fixture covers every
combination of (party-account ✕ monitored-hashtag).

### Things to keep in mind

- **JSON dict keys become strings.** A field like `hashtags_by_pol_video:
  dict[int, list[str]]` round-trips through `JSONField` with string keys. If
  you read it back and need `int` keys, cast at the edge.
- **Persisted stats are a snapshot, not a live view.** Once a participant's
  row exists, regenerating after upstream metadata changes does **not**
  happen automatically. If you change the political-video definition and want
  existing participants' reports to reflect the change, you need to delete
  the old `ParticipantReportStatistics` row (the next view will recompute) 
  or trigger a re-compute (the view will render the most recent statistics object).
- **`PARTIES_ORDER` is the ordering authority.** Anything user-visible that
  iterates parties should respect this order; `_party_sort_key` in
  `services.py` is the shared sort key — reuse it.
- **The synthetic preview** is reached at `/report/get/synthetic/`. Use it
  during development: it gives you a populated report without touching the
  donation flow.
