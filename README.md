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
