from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import TikTokConnection, TikTokDataRequest


class TikTokConnectionIsExpiredTest(TestCase):
    def setUp(self):
        self.connection = TikTokConnection.objects.create(
            open_id="test_open_id",
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            token_type="Bearer",
            scope="user.info.basic",
        )

    def test_expired_when_no_expiry_set(self):
        self.connection.access_token_expires_at = None
        self.assertTrue(self.connection.is_expired())

    def test_not_expired_when_expiry_in_future(self):
        self.connection.access_token_expires_at = timezone.now() + timedelta(hours=1)
        self.assertFalse(self.connection.is_expired())

    def test_expired_when_expiry_in_past(self):
        self.connection.access_token_expires_at = timezone.now() - timedelta(seconds=1)
        self.assertTrue(self.connection.is_expired())

    def test_not_expired_without_threshold(self):
        self.connection.access_token_expires_at = timezone.now() + timedelta(seconds=30)
        self.assertFalse(self.connection.is_expired())

    def test_expired_with_threshold_exceeding_remaining_time(self):
        self.connection.access_token_expires_at = timezone.now() + timedelta(seconds=30)
        self.assertTrue(self.connection.is_expired(threshold=60))

    def test_not_expired_with_threshold_below_remaining_time(self):
        self.connection.access_token_expires_at = timezone.now() + timedelta(
            seconds=120
        )
        self.assertFalse(self.connection.is_expired(threshold=60))


class TikTokConnectionRefreshIsExpiredTest(TestCase):
    def setUp(self):
        self.connection = TikTokConnection.objects.create(
            open_id="test_open_id",
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            token_type="Bearer",
            scope="user.info.basic",
        )

    def test_expired_when_no_expiry_set(self):
        self.connection.refresh_token_expires_at = None
        self.assertTrue(self.connection.refresh_is_expired())

    def test_not_expired_when_expiry_in_future(self):
        self.connection.refresh_token_expires_at = timezone.now() + timedelta(days=30)
        self.assertFalse(self.connection.refresh_is_expired())

    def test_expired_when_expiry_in_past(self):
        self.connection.refresh_token_expires_at = timezone.now() - timedelta(seconds=1)
        self.assertTrue(self.connection.refresh_is_expired())

    def test_expired_with_threshold_exceeding_remaining_time(self):
        self.connection.refresh_token_expires_at = timezone.now() + timedelta(
            seconds=30
        )
        self.assertTrue(self.connection.refresh_is_expired(threshold=60))

    def test_not_expired_with_threshold_below_remaining_time(self):
        self.connection.refresh_token_expires_at = timezone.now() + timedelta(
            seconds=120
        )
        self.assertFalse(self.connection.refresh_is_expired(threshold=60))


class TikTokDataRequestIsActiveTest(TestCase):
    def _create_request(self, status, download_succeeded=False):  # noqa: FBT002
        return TikTokDataRequest(
            open_id="test_open_id",
            request_id=12345,
            status=status,
            download_succeeded=download_succeeded,
        )

    def test_active_when_not_polled(self):
        req = self._create_request(TikTokDataRequest.State.NOT_POLLED)
        self.assertTrue(req.is_active())

    def test_active_when_pending(self):
        req = self._create_request(TikTokDataRequest.State.PENDING)
        self.assertTrue(req.is_active())

    def test_active_when_ready(self):
        req = self._create_request(TikTokDataRequest.State.READY)
        self.assertTrue(req.is_active())

    def test_inactive_when_expired(self):
        req = self._create_request(TikTokDataRequest.State.EXPIRED)
        self.assertFalse(req.is_active())

    def test_inactive_when_cancelled(self):
        req = self._create_request(TikTokDataRequest.State.CANCELLED)
        self.assertFalse(req.is_active())

    def test_active_when_expired_but_download_succeeded(self):
        req = self._create_request(
            TikTokDataRequest.State.EXPIRED, download_succeeded=True
        )
        self.assertTrue(req.is_active())

    def test_active_when_cancelled_but_download_succeeded(self):
        req = self._create_request(
            TikTokDataRequest.State.CANCELLED, download_succeeded=True
        )
        self.assertTrue(req.is_active())
