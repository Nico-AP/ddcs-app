# Documentation of the Website

The public-facing site — landing page, info pages, navigation, footer — is
handled by the `ddcs.website` app. It is the front door for participants:
everything they see before they enter the donation flow lives here. Also
anything related to public outreach and directed at other stakeholders 
lives here.

The site is a **Wagtail CMS** instance. Wagtail is a Django-based content
management system: pages, page content, navigation, and most copy are edited
through the Wagtail admin rather than by changing code. Developers add new
**block types** and **page types**; content editors compose pages from those
blocks (through the admin GUI).

## What's in here

- [`models.py`](../ddcs/website/models.py) — defines `SitePage` (the single page
  type the site uses) and the `StreamField` blocks that can be placed on it:
  hero, sections, card grids, navigation, etc. Editors mix and match these in
  the Wagtail admin to build pages.
- [`templates/website/`](../ddcs/website/templates/website) — base layout
  (`base.html`), the site header/footer, and per-block component templates
  referenced from `models.py`.
- [`static/website/`](../ddcs/website/static/website) — site-specific images,
  fonts, and JS. Shared CSS lives in `ddcs.core`.
- [`context_processors.py`](../ddcs/website/context_processors.py) — injects
  site-wide context (e.g. navigation settings) into every template render.
- [`rich_text.py`](../ddcs/website/rich_text.py) — customizations to Wagtail's
  rich-text editor (allowed tags/features).
- [`fixtures/`](../ddcs/website/fixtures) — seed content used to bootstrap a
  fresh database. See [the fixture README](../ddcs/website/fixtures/README.md).

## Setup

After cloning and following the [main README](../README.md) setup, do the
following Wagtail-specific steps:

1. **Load the fixture** (one-time, on a fresh database):
   ```bash
   python manage.py loaddata wagtail_fixture.json
   ```
   This creates the root page tree and a starter `SitePage`. If you hit an
   `IntegrityError` on Wagtail's `Page.path`, see the
   [fixture README](../ddcs/website/fixtures/README.md) for the cleanup.

2. **Log in to the Wagtail admin** at `/admin/pages/` (Django superuser
   credentials). From there you can edit page copy, swap images, reorder
   navigation, etc., without touching code.

3. **Edit navigation** under *Settings → Navigation Settings* in the Wagtail
   admin. This is backed by `NavigationSettings`
   (a `BaseSiteSetting`) in [`models.py`](../ddcs/website/models.py).

## Configuration

There are no `ddcs.website`-specific environment variables; the app inherits
Wagtail's site/host configuration from the standard Django/Wagtail setup
(`SITE_ID`, the Wagtail `Site` model, `ALLOWED_HOSTS`).

When deploying to a new domain:

- Update the Wagtail `Site` row (admin → Settings → Sites) so the hostname
  matches the deployment domain.
- Ensure media uploads and the compiled CSS bundle
  (`ddcs/core/static/core/css/ddcs.css`) are served by your static-file
  backend.

## Adding new page content (no code)

Most edits are pure CMS work:

- Edit existing pages: Wagtail admin → *Pages* → choose page → edit body
  StreamField.
- Add a new page: create a new `SitePage` under an existing parent. Compose its
  body from the available blocks.
- Add a new top-level link: edit *Navigation Settings*.

## Adding a new block type (code)

When editors need a layout the existing blocks can't produce, add a new
`StructBlock` in [`models.py`](../ddcs/website/models.py) following the
pattern of `HeroBlock` / `SectionBlock`:

1. Define the block class with its sub-fields.
2. Reference a template in its `Meta.template`
   (`website/components/<name>.html`).
3. Add the new block to `SitePage.body`'s `StreamField` field list.
4. Create the matching template under
   [`templates/website/components/`](../ddcs/website/templates/website/components).
5. Run `python manage.py makemigrations` — Wagtail tracks StreamField
   composition in migrations.

## i18n

Site copy is in German by default. Source strings inside templates and Python
modules use `{% trans %}` / `gettext_lazy`. See the
[i18n section of the main README](../README.md#translations--internationalization)
for the workflow.

Page content edited through the Wagtail admin is not translated through the
`.po` workflow — it lives in the CMS as plain text in whichever language an
editor types it.
