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
