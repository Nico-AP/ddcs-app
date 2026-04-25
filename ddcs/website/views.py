from csp.constants import UNSAFE_INLINE
from csp.decorators import csp_update
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView


# The parts copied from the 2025 website contain a lot of inline styles and sources
#  not worth refactoring.
@method_decorator(
    csp_update({"img-src": "data:", "style-src": UNSAFE_INLINE}), name="dispatch"
)
class DFDW2025PageView(TemplateView):
    template_name = "website/dfdw_2025/base.html"


# ---- Exception Views ----


def custom_400(request: HttpRequest, exception: Exception) -> HttpResponse:
    template = "exceptions/400.html"
    return render(request, template, status=400)


def custom_403(request: HttpRequest, exception: Exception) -> HttpResponse:
    template = "exceptions/403.html"
    return render(request, template, status=403)


def custom_404(request: HttpRequest, exception: Exception) -> HttpResponse:
    template = "exceptions/404.html"
    return render(request, template, status=404)


def custom_500(request: HttpRequest) -> HttpResponse:
    template = "exceptions/500.html"
    return render(request, template, status=500)
