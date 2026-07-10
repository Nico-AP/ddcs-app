# Data Donation as Citizen Science (DDCS) Application

The repository holds the codebase of the main DDCS web application.

## Development Setup

### Prerequisites

| Tool          | Version         | Notes                                   |
|---------------|-----------------|-----------------------------------------|
| Python        | 3.12            | Use pyenv or a system package           |
| Node.js + npm | any current LTS | Required for CSS compilation            |
| Git           | any             | Pre-commit hooks are used               |
| gettext       | any             | Required for compiling translations     |

PostgreSQL is only needed in production. Local development uses SQLite.

---

### Initial Setup

#### 1. Clone the repository

```bash
git clone https://github.com/Nico-AP/ddcs-app
cd ddcs-app
```

#### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows
```

#### 3. Install Python dependencies

```bash
pip install -r requirements/dev.txt
```

#### 4. Set up environment variables

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```
DJANGO_SETTINGS_MODULE=config.settings.local
SECRET_KEY=<any-random-string>   # generate with: python -c "import secrets; print(secrets.token_urlsafe(50))"
```

All other variables have sensible local defaults. Email is printed to the console and the database is SQLite — no further configuration is needed for local development.

#### 5. Install pre-commit hooks

```bash
pre-commit install
pre-commit install --hook-type pre-push   # enables pip-audit on push
```

#### 6. Apply database migrations

```bash
python manage.py migrate
```

#### 7. Create a superuser

```bash
python manage.py createsuperuser
```

#### 8. Compile translations

```bash
python manage.py compilemessages
```

#### 9. Install CSS dependencies

```bash
cd .sass && npm install && cd ..
```

Start the CSS watcher so styles rebuild on save:

```bash
cd .sass && npm run sass:watch
```

#### 10. Start the development server

```bash
python manage.py runserver
```

The app is now available at http://127.0.0.1:8000. The Django admin is at the URL set by `ADMIN_URL` (default: `admin/`).

---

## Repository Management


### Branches

We work with three central branches:

- `dev`: Shared code, pre-deployment;
- `stage`: Deployed to stage for testing and QA before production.
- `main`: Deployed to production.

All three branches are protected: no direct pushes, all changes land via PR
(with CI checks passing and branches required to be up to date before merge).

### Normal Development Workflow

1. Create local branch (e.g., `feat/something-nice` / `refactor/reports` etc.)
   from `dev`:

```bash
git checkout dev
git pull origin dev
git checkout -b feat/something-nice
```

2. Work and commit locally on `feat/something-nice`

```bash
git add .
git commit -m "feat: app now talks to ghosts"
```

3. When the new code is ready to be integrated into the shared codebase, ensure
   it is still in sync with the shared codebase on `dev` and resolve conflicts
   if necessary. Also do this regularly (e.g., daily) if work is carried out
   over a longer time.

```bash
git checkout dev
git pull origin dev
git checkout feat/something-nice
git merge dev  # or rebase
# resolve conflicts and commit again if needed.
```

4. Push your local branch to the repository:

```bash
git push -u origin feat/something-nice
```

5. Go to github.com and open a Pull Request (PR; through "Compare & pull request").

6. In the web UI, Review the diff yourself, or tag someone else to review it. Wait for CI (lint, tests) to pass.

7. In the web UI, merge PR (use __squash__)

8. Back in your IDE, sync and clean up:

```bash
git checkout dev
git pull origin dev
git branch -d feat/something-nice
git push origin --delete feat/something-nice
```

### Promoting to Stage (QA)

Once one or more updates on `dev` are ready to be tested on the server,
promote `dev` to `stage`.

1. Announce in the chat that you're promoting to stage (so the other person isn't
   surprised by a deploy).

2. Promote `dev` to `stage` through pull request:

```bash
git checkout dev
git pull origin dev
git push origin dev  # ensures remote dev is current
gh pr create --base stage --head dev --title "Promote dev to stage: $(date +%Y-%m-%d)"
# review diff in browser, wait for CI, merge (use 'merge commit')
```

3. Run the stage deployment playbook from the ddcs-infra repo.

4. Test updates on the stage server. Fix bugs found here as normal commits on `dev`
   (via a `fix/...` branch and PR, same as any other change),
   then repeat steps 2–3 to re-promote.

`stage` is protected: no direct pushes, only merges via PR from `dev` or `hotfix/*`
(see below).

---

### Tags

Every production release gets a tag on `main`, created right after the
promotion PR merges and before deployment. The tag is required by the
ddcs-infra playbook that handles the production deployment -
it uses the tag to pull the correct code version.

Tags are a plain, incrementing counter (`r1`, `r2`, `r3`, ...).

Tags are important for:

- **Knowing what is deployed** — production deployments are always linked to
  a specific tag/release, never `main` directly. So what's on prod is exactly
  what we decided to ship, even if `main` moves forward again before the deploy runs.
- **Rollback target** — redeploy a known-good tag without hunting for the
  right commit SHA.
- **Reference point for debugging** — "this broke after r10" is a lot more
  useful than "sometime last week."
- **Changelog for free** — `git log r9..r10` shows exactly what shipped in
  a release, assuming PR titles follow commit hygiene below.


### Promoting to Production (Release)

Once `stage` has been tested and is ready for release:

1. Announce in chat that you're releasing to production, and — if not already known —
   what the update includes.

2. Find the latest release tag, to name the PR (the actual tag is created
   later, in step 4):

```bash
git tag --list 'r[0-9]*' | sort -V | tail -1
```

This returns, e.g., `r10`. This means the next release will be `r11`.

3. Promote `stage` to `main` through pull request:

```bash
git checkout stage
git pull origin stage
gh pr create --base main --head stage --title "Release r11"
# review diff, wait for CI, merge (merge commit)
```

4. After merging the PR int main, tag the release:

```bash
git checkout main
git pull origin main
git tag r11
git push origin --tags
```

5. Run the production deployment playbook from the ddcs-infra repo, targeting `r11`.

6. Confirm the app is healthy on prod (quick smoke check).


`main` is protected: no direct pushes, only merges via PR from `stage` or
`hotfix/*`.

---

### Hotfixes

For urgent production bugs that can't wait for the normal `dev` → `stage` → `main` cycle:

1. Branch off `main` directly:

```bash
git checkout main
git pull origin main
git checkout -b hotfix/short-description
```

2. Fix, commit, push, open a PR into `main` (same PR flow as normal development,
   base = `main` instead of `dev`).

3. Merge the PR using **merge commit**, not squash, to match `main`'s
   convention. Then tag and deploy to production as in "Promoting to
   Production" above (find next tag, tag, deploy targeting the tag, smoke
   check, log the release).

4. **Important: Merge the fix back into `stage` and `dev`** so they don't drift
   out of sync with `main`:

```bash
gh pr create --base stage --head main --title "Sync hotfix into stage"
# review diff, wait for CI, merge (use merge commit, not squash)

git checkout dev
git pull origin dev
gh pr create --base dev --head stage --title "Sync hotfix into dev"
# review diff, wait for CI, merge (use merge commit, not squash)
```


### Commit Hygiene

**Feature branches:** commit however works for you — messy, frequent,
"wip"/"fix"/"actually fix" is fine. These commits get squashed away and
never appear in `dev` history, so there's no need to keep them clean.

**PR titles matter** — since squash merge uses the PR title as the
final commit message on `dev`, the PR title is the one thing that becomes
permanent history. Write it as a semantic commit:

`<type>(<apps it touches>): <short description>`

Common types:

| Type       | Use for                                     |
|------------|---------------------------------------------|
| `feat`     | new functionality                           |
| `style`    | visual/UI-only change, no logic change      |
| `fix`      | bug fix                                     |
| `refactor` | code change with no behavior change         |
| `chore`    | tooling, deps, config, non-code maintenance |
| `docs`     | documentation only                          |

Examples:

- `feat(metadata): add scraper`
- `style(reports): update button styling`
- `fix(website): missing closing tag in hero template`
- `chore: update sass script`
- `refactor(reports): move metrics into dedicated package`

Keep the description short and in the imperative mood ("add X", not "added X"
or "adds X"). This keeps `git log` on `dev`/`main` readable as a changelog
and makes `git bisect` and tag-range diffs (`git log r9..r10`) actually useful.

## Day-to-day Development

### Running tests

```bash
python -m coverage run manage.py test
python -m coverage report          # fails if coverage drops below 80 %
```

### Linting and formatting

Usually, auto-run when committing, but good to know:

```bash
ruff check .                        # lint
ruff check . --fix                  # lint and auto-fix
ruff format .                       # format
djlint ddcs/ --check                # check templates
djlint ddcs/ --reformat             # reformat templates
```

### Building CSS for production

```bash
cd .sass && npm run sass:build
```

Outputs a compressed stylesheet without source maps to `ddcs/core/static/core/css/ddcs.css`.

### Skipping pre-commit hooks

To skip a specific hook (e.g. when a vulnerability has no fix yet):

```bash
SKIP=pip-audit git push
```

To skip all hooks — use sparingly:

```bash
git push --no-verify
```

`SKIP` accepts a comma-separated list of hook IDs: `SKIP=pip-audit,check-translations git push`.

---

## Translations / Internationalization

The site defaults to German (`de-de`). Source strings are written in English; the German `.po` file provides translations.

### Adding translatable strings

**Python** (views, models, forms):
```python
from django.utils.translation import gettext_lazy as _

label = _("Your string here")
```

**Templates:**
```html
{% load i18n %}

{% trans "Your string here" %}

{# With variables #}
{% blocktrans with name=user.name %}Hello, {{ name }}{% endblocktrans %}
```

### Updating translation files

After adding new strings:

```bash
# Extract new strings into the .po file (also removes obsolete entries)
python manage.py makemessages -l de --no-obsolete

# Translate the new entries in locale/de/LC_MESSAGES/django.po, then compile:
python manage.py compilemessages
```

The pre-commit hook will block commits that introduce untranslated strings — it runs `makemessages` and fails if the `.po` file changes.
Stage the updated `.po` file together with your code changes.

Translation files are located at `locale/de/LC_MESSAGES/django.po`.

### Adding a new language

1. Add the language to `LANGUAGES` in `config/settings/base.py`
2. Run `python manage.py makemessages -l <language_code>`
3. Translate strings in `locale/<language_code>/LC_MESSAGES/django.po`
4. Run `python manage.py compilemessages`
