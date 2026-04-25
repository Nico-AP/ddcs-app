Load the fixture with:

```bash
python manage.py loaddata wagtail_fixture.json
```

If it fails due to a Integrity Error (UNIQUE constraint failed: wagtailcore_page.path), then run the following.
Only do so if you haven't created and modified any wagtail pages, otherwise this will be deleted.

```bash
python manage.py shell
```

```python
from wagtail.models import Page
Page.objects.filter(depth=1).delete()
```

Afterward, try again to load the fixtures.
