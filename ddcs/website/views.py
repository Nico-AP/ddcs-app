from csp.constants import UNSAFE_INLINE
from csp.decorators import csp_update
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView


class LandingPageView(TemplateView):
    template_name = "website/landing_page/base.html"


class ImpressumView(TemplateView):
    template_name = "website/impressum/base.html"


class DataProtectionStatementView(TemplateView):
    template_name = "website/dps/base.html"


# The parts copied from the 2025 website contain a lot of inline styles and sources
#  not worth refactoring.
@method_decorator(
    csp_update({"img-src": "data:", "style-src": UNSAFE_INLINE}), name="dispatch"
)
class DFDW2025PageView(TemplateView):
    template_name = "website/dfdw_2025/base.html"
