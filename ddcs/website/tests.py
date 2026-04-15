from django.test import Client, TestCase
from django.urls import reverse


class WebsiteTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_landing_page(self):
        """Test that the landing page returns a 200 status code."""
        url = reverse("website:landing_page")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
