from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from ddcs.website.context_processors import analytics


class WebsiteTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_landing_page(self):
        """Test that the landing page returns a 200 status code."""
        url = reverse("website:landing_page")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_impressum_page(self):
        """Test that the imprint page returns a 200 status code."""
        url = reverse("website:impressum")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_dps_page(self):
        """Test that the data protection statement page returns a 200 status code."""
        url = reverse("website:dps")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_dfdw_2025_page(self):
        """Test that the DFDW 2025 page returns a 200 status code."""
        url = reverse("website:dfdw_2025")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class AnalyticsProcessorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(
        ANALYTICS_SCRIPT_SRC="https://example.com", ANALYTICS_WEBSITE_ID="12345"
    )
    def test_analytics_processor_returns_correct_values(self):
        request = self.factory.get("/")
        result = analytics(request)

        self.assertEqual(result["ANALYTICS_SCRIPT_SRC"], "https://example.com")
        self.assertEqual(result["ANALYTICS_WEBSITE_ID"], "12345")

    @override_settings(ANALYTICS_WEBSITE_ID=None)
    def test_analytics_processor_handles_none_values(self):
        request = self.factory.get("/")
        result = analytics(request)

        self.assertIsNone(result["ANALYTICS_WEBSITE_ID"])
