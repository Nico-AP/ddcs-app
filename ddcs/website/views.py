from django.views.generic import TemplateView


class LandingPageView(TemplateView):
    template_name = "website/landing_page/base.html"


class ImpressumView(TemplateView):
    template_name = "website/impressum/base.html"


class DataProtectionStatementView(TemplateView):
    template_name = "website/dps/base.html"


class DFDW2025PageView(TemplateView):
    template_name = "website/dfdw_2025/base.html"
