from django.urls import reverse
from two_factor.views import LoginView


class Admin2FALoginView(LoginView):
    def get_success_url(self) -> str:
        return self.get_redirect_url() or reverse("admin:index")


class CMS2FALoginView(LoginView):
    def get_success_url(self) -> str:
        return self.get_redirect_url() or reverse("wagtailadmin_home")
