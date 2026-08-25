from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404, HttpRequest
from django.urls import include, path
from django.views.generic import TemplateView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.contrib.sitemaps.views import sitemap
from wagtail.documents import urls as wagtaildocs_urls

from ddcs.auth.views import Admin2FALoginView, CMS2FALoginView


def force_404_view(request: HttpRequest) -> None:
    """Simple 404 view used to overwrite ddm login endpoints"""
    raise Http404


urlpatterns = [
    # Auth (overrides base admin and CMS login views).
    path(f"{settings.ADMIN_URL}/login", Admin2FALoginView.as_view(), name="login"),
    path("cms/login/", CMS2FALoginView.as_view(), name="wagtailadmin_login"),
    # Admin
    path(f"{settings.ADMIN_URL}/", admin.site.urls),
    # DDCS
    path("", include("ddcs.website.urls", namespace="website")),
    path("metadata/", include("ddcs.metadata.urls", namespace="metadata")),
    path("", include("ddcs.datadonation.urls", namespace="datadonation")),
    path("", include("ddcs.reports.urls", namespace="reports")),
    # DRF
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # DDM
    path("ddm/", include("ddm.core.urls")),
    path("ddm/login/", force_404_view, name="ddm_login"),
    path("ddm/logout/", force_404_view, name="ddm_logout"),
    path("ckeditor5/", include("django_ckeditor_5.urls")),
    # CMS - Wagtail
    path("cms/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path(
        "robots.txt",
        TemplateView.as_view(
            template_name="website/robots.txt", content_type="text/plain"
        ),
    ),
    path("sitemap.xml", sitemap, name="sitemap"),
]

if settings.DEBUG:
    from debug_toolbar.toolbar import debug_toolbar_urls  # Must be imported here

    urlpatterns += debug_toolbar_urls()
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += [path("", include(wagtail_urls))]

handler400 = "ddcs.website.views.custom_400"
handler403 = "ddcs.website.views.custom_403"
handler404 = "ddcs.website.views.custom_404"
handler500 = "ddcs.website.views.custom_500"
