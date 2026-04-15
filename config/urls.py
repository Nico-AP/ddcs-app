from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(f"{settings.ADMIN_URL}", admin.site.urls),
    path("", include("ddcs.website.urls", namespace="website")),
]

if settings.DEBUG:
    from debug_toolbar.toolbar import debug_toolbar_urls  # Must be imported here

    urlpatterns += debug_toolbar_urls()
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
