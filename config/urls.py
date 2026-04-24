from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from two_factor.urls import urlpatterns as tf_urls

urlpatterns = [
    path(f"{settings.ADMIN_URL}", admin.site.urls),
    path("", include("ddcs.website.urls", namespace="website")),
    path("", include("ddcs.datadonation.urls", namespace="datadonation")),
    # 2FA
    path("", include(tf_urls)),
    # DDM
    path("ddm/", include("ddm.core.urls")),
    path("ckeditor5/", include("django_ckeditor_5.urls")),
]

if settings.DEBUG:
    from debug_toolbar.toolbar import debug_toolbar_urls  # Must be imported here

    urlpatterns += debug_toolbar_urls()
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


handler400 = "ddcs.website.views.custom_400"
handler403 = "ddcs.website.views.custom_403"
handler404 = "ddcs.website.views.custom_404"
handler500 = "ddcs.website.views.custom_500"
