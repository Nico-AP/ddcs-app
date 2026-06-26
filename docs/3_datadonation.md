# Documentation of the Data Donation Flow

The `ddcs.datadonation` app drives the part of the participant's journey where
they actually hand over their TikTok data. It then triggers the downstream
processing that produces metadata and a personalized report.

There are **two ways** a participant can donate:

1. **Download-Upload.** The participant requests their data export from TikTok,
   downloads the ZIP, and uploads it to us.
2. **Portability flow.** The participant authorizes us via TikTok's OAuth, and
   we request the export on their behalf and pull it directly when ready.
   Lives under [`ddcs.datadonation.portability`](../ddcs/datadonation/portability).
   Access to the Portability API is still under review by TikTok.

Both paths feed into the same DDM-based donation step and the same
post-processing pipeline.

The heavy lifting around storing/encrypting donations and matching them to a
"donation project" is provided by **DDM** (`django-ddm`). This app is the
project-specific glue around it.

## What's in here

| File / package                                                                                                      | Purpose                                                                                                                                                                                       |
|---------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`views.py`](../ddcs/datadonation/views.py)                                                                         | `DonationViewDDM` (ZIP upload step) and `DebriefingView`. Both subclass DDM views and override the project/step initialization.                                                               |
| [`services.py`](../ddcs/datadonation/services.py)                                                                   | Decrypts donations, normalises records (date parsing, key normalisation), maps to the `TikTokUserData` dataclass; `post_process_donation()` is the entry point called after a donation lands. |
| [`config.py`](../ddcs/datadonation/config.py)                                                                       | Project slug and blueprint names — must match what is configured in the DDM admin (see [Setup](#setup)).                                                                                      |
| [`portability/`](../ddcs/datadonation/portability)                                                                  | TikTok-OAuth portability sub-flow (see below).                                                                                                                                                |
| [`urls.py`](../ddcs/datadonation/urls.py)                                                                           | Routes for the donation step and the debriefing.                                                                                                                                              |
| [`templates/datadonation/`](../ddcs/datadonation/templates/datadonation)                                            | Donation, debriefing, and portability templates.                                                                                                                                              |
| [`management/commands/create_tiktok_project.py`](../ddcs/datadonation/management/commands/create_tiktok_project.py) | Bootstraps the DDM project + blueprints with the right slug/names.                                                                                                                            |

## The participation flow

The DDM `Participant` walks through these steps (see
`PARTICIPATION_FLOW_STEPS` in [`views.py`](../ddcs/datadonation/views.py)):

1. **Donation step** (`datadonation:donation_ddm`) — ZIP upload UI, or the
   portability hand-off. After a successful upload DDM stores encrypted
   donations and we then call `post_process_donation(participant)`, which:
   - fetches and decrypts the donations via `get_user_data()`;
   - calls `register_donation_metadata()` (in
     [`ddcs.metadata.services`](../ddcs/metadata/services.py)) so any new
     videos/users discovered in the donation enter the registry;
   - calls `generate_report_statistics()` (in
     [`ddcs.reports.services`](../ddcs/reports/services.py)) so the participant's
     report is precomputed.
2. **Questionnaire step** (`ddm_participation:questionnaire`) — managed entirely
   by DDM, configured in the DDM admin.
3. **Debriefing step** (`datadonation:debriefing`) — links to the participant's
   report (`reports:report` with the `external_id`).

## The portability flow

[`ddcs.datadonation.portability`](../ddcs/datadonation/portability) implements
the OAuth-based alternative to the ZIP upload. The participant clicks
*"Authorize TikTok"*; we:

1. Redirect them through TikTok's authorize URL.
2. Receive the callback, exchange the code for tokens, and persist a
   `TikTokConnection`.
3. Request a data export via TikTok's portability API and persist a
   `TikTokDataRequest` row tracking its state (`NOT_POLLED → PENDING → READY →
   downloaded`).
4. Once the file is ready, download it and feed it into the same DDM donation
   step the ZIP-upload path uses.

OAuth client setup lives in
[`portability/oauth.py`](../ddcs/datadonation/portability/oauth.py).

## Setup

### 1. Environment variables (TikTok credentials)

These belong in `.env`. The portability flow requires its own OAuth app
registered at TikTok Developers.

| Variable                     | Used for                                       | Where it's read                                                                                     |
|------------------------------|------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| `TIKTOK_CLIENT_ID`           | Portability OAuth client ID                    | [`portability/oauth.py`](../ddcs/datadonation/portability/oauth.py)                                 |
| `TIKTOK_CLIENT_SECRET`       | Portability OAuth client secret                | [`portability/oauth.py`](../ddcs/datadonation/portability/oauth.py)                                 |
| `TIKTOK_RESEARCH_API_KEY`    | Research API (for metadata enrichment)         | [`ddcs.metadata.research_api`](../ddcs/metadata/research_api) — see [4_metadata.md](4_metadata.md). |
| `TIKTOK_RESEARCH_API_SECRET` | Research API                                   | as above                                                                                            |

Without `TIKTOK_CLIENT_ID`/`TIKTOK_CLIENT_SECRET`, only the ZIP-upload donation
path works; the portability flow will fail.

### 2. Create the DDM project

DDM needs a `DonationProject` row whose slug and blueprint names match the
constants in [`config.py`](../ddcs/datadonation/config.py):

```python
DDM_TIKTOK_PROJECT_SLUG = "tiktok"
WATCH_HISTORY_BP_NAME   = "watch_history"
FOLLOWED_BP_NAME        = "followed_accounts"
LIKED_VIDEOS_BP_NAME    = "liked_videos"
```

The easiest way is the management command:

```bash
python manage.py create_tiktok_project 1
```
Where "1" refers to the (super)users ID that administrates the ddm instance.
This creates the project and the three blueprints with the expected slugs. If
you instead create them by hand through the DDM admin (`/ddm/projects/`), make
sure the slug and blueprint names are character-for-character identical to the
constants above — they are how `services.py` looks up the donations.

Renaming any of those should be done in **both** places at once: the constant
in `config.py` and the corresponding DDM admin entry.

IN LOCAL DEV: Before `/ddm/projects/` - open `http://127.0.0.1:8000/admin/login/` to login with superuser and then open

`http://127.0.0.1:8000/ddm/projects/` to continue. there are some issue with url paths in the repro CHECK LATER

### 3. (Optional) Adjust the participation flow

If you add or remove a participant step (e.g. an extra debriefing variant),
update `PARTICIPATION_FLOW_STEPS` in
[`views.py`](../ddcs/datadonation/views.py) and the matching URL names. The
DDM step machinery uses this list to navigate forward.

## Post-donation processing

`post_process_donation(participant)` runs **synchronously** after the upload
finishes, currently. It is the integration point with the metadata and reports
apps — see [6_data_pipeline.md](6_data_pipeline.md) for the full chain.

**Known TODO:** this should move to a Celery task once we measure how long
the pipeline takes on real-world donations; today it blocks the upload
response.
