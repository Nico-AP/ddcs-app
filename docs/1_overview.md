# DDCS — Project Overview

**Data Donation as Citizen Science (DDCS)** is a Django web application that lets
TikTok users donate their personal TikTok usage data — watch history, followed accounts,
liked videos — to a research project and receive a personalized report about the
political content they have been exposed to.

The user-facing flow is:

1. Land on the public website and give consent to participate.
2. Either upload a TikTok data-export ZIP **or** authorize a "data portability"
   flow that pulls the same data straight from TikTok (the portability path depends on
   access to the Portability API which has not yet been granted).
3. Answer a short questionnaire.
4. See a debriefing page that links to their personal **report**.

In the background the app maintains an evolving registry of **political TikTok
content** (party accounts and accounts using monitored hashtags), kept current
via TikTok's Research API and through scraping (scraping still needs to be implemented). 
The participant's donated data is intersected with this registry to produce the report.

## The apps

Each Django app under `ddcs/` is documented in its own file.

| App                                      | Purpose                                                                                                                       | Docs                                   |
|------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|----------------------------------------|
| [`ddcs.website`](2_website.md)           | Public website, landing/info pages, navigation. Wagtail-backed CMS.                                                           | [2_website.md](2_website.md)           |
| [`ddcs.datadonation`](3_datadonation.md) | Donation flow: ZIP upload **and** TikTok-OAuth portability. Entry to post-donation pipeline.                                  | [3_datadonation.md](3_datadonation.md) |
| [`ddcs.metadata`](4_metadata.md)         | Registry of TikTok videos/users/hashtags/music; enrichment via Research API + scraper.                                        | [4_metadata.md](4_metadata.md)         |
| [`ddcs.reports`](5_reports.md)           | Per-participant report (plots + wordclouds + top videos) based on donated data. Public report (still needs to be implemented) | [5_reports.md](5_reports.md)           |
| `ddcs.core`                              | Shared assets (SCSS, base templates), context processors, common types.                                                       | —                                      |
| `ddcs.auth`                              | Two-factor-auth shell around the Django admin login.                                                                          | —                                      |

For details on the end-to-end data flow that spans donation → metadata → report, see
[6_data_pipeline.md](6_data_pipeline.md).

## Stack at a glance

- **Backend:** Django 5.2 + Wagtail CMS (public site) + DDM
  (`django-ddm`, donation framework).
- **Async:** Celery + Redis. Scheduled tasks via `django-celery-beat`.
- **DB:** SQLite for local dev; PostgreSQL in production.
- **Frontend:** Django templates + HTMX for partial updates. SCSS compiled via
  `.sass/` (Node). Plots via Plotly. Donation interface from DDM via webpack.
- **Auth:** Django + `django-two-factor-auth` for admin; participant flow uses
  random 24-char `external_id` tokens as capability URLs.
- **Encryption:** donated payloads stored encrypted via
  `django-fernet-encrypted-fields` + DDM's `Decryption` helper.
- **i18n:** site is German by default (`de-de`); English source strings live in
  `locale/de/LC_MESSAGES/django.po`.

## Repository layout (top-level)

```
ddcs-app/
├── config/             # Django settings, URLs, Celery, ASGI/WSGI
├── ddcs/               # Project apps (see table above)
├── docs/               # This documentation
├── locale/             # Translations (.po files)
├── logs/               # Rotating log output (dev)
├── requirements/       # Layered pip requirements
├── .sass/              # Node tooling for SCSS → CSS
└── manage.py
```

## Setting up the project

Setup, day-to-day commands (tests, linting, translations, CSS), and pre-commit
hooks are documented in the [top-level README](../README.md). The per-app
docs in this folder assume that setup is already done and focus on what each
app does and how to configure it.

## Where to look first

- **"How does a donation become a report?"** → [6_data_pipeline.md](6_data_pipeline.md).
- **"How do I add a new section to the report?"** → [5_reports.md](5_reports.md#extending-the-report).
- **"How do I add a new account or hashtag to monitor?"** → [4_metadata.md](4_metadata.md#populating-the-registry).
- **"How do I edit the public site copy?"** → [2_website.md](2_website.md) — almost everything is editable through the Wagtail admin.
