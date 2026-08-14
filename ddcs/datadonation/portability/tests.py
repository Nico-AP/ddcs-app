from datetime import timedelta
from unittest.mock import MagicMock, patch

from authlib.integrations.base_client import OAuthError
from ddm.participation.models import Participant
from ddm.participation.views import get_participation_session_id
from ddm.projects.models import DonationProject, ResearchProfile
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from requests.exceptions import HTTPError

from ddcs.datadonation.portability.models import TikTokConnection, TikTokDataRequest
from ddcs.datadonation.portability.services import get_valid_token
from ddcs.datadonation.portability.views import hash_open_id


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
    def setUp(self):
        self.connection = TikTokConnection.objects.create(
            open_id="test_open_id",
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            token_type="Bearer",
            scope="user.info.basic",
        )

    def _create_request(self, status, download_succeeded=False):  # noqa: FBT002
        return TikTokDataRequest(
            connection=self.connection,
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


class PortabilityViewTestCase(TestCase):
    """Base class providing a donation project, a participant, and a session
    seeded the way `ddm.participation.views.create_participation_session` does.
    """

    def setUp(self):
        user = get_user_model().objects.create_user(
            username="researcher", password="test-pass"
        )
        owner_profile = ResearchProfile.objects.create(user=user)
        self.project = DonationProject.objects.create(
            name="TikTok",
            slug=settings.TIKTOK_DDM_PROJECT_SLUG,
            contact_information="test@example.com",
            data_protection_statement="test",
            owner=owner_profile,
        )
        self.participant = Participant.objects.create(
            project=self.project,
            external_id="x" * 24,
            start_time=timezone.now(),
        )
        self._seed_participant_session()

    def _seed_participant_session(self):
        session = self.client.session
        session_id = get_participation_session_id(self.project)
        session[session_id] = {"participant_id": self.participant.id}
        session.save()

    def _seed_connection_session(self, connection):
        session = self.client.session
        session["tiktok_connection_id"] = connection.id
        session.save()

    def _create_connection(self, open_id="raw_open_id"):
        return TikTokConnection.objects.create(
            open_id=hash_open_id(open_id),
            access_token="access-token",
            refresh_token="refresh-token",
            access_token_expires_at=timezone.now() + timedelta(hours=1),
            refresh_token_expires_at=timezone.now() + timedelta(days=30),
            token_type="Bearer",
            scope="user.info.basic",
        )


class ParticipantInSessionMixinTest(PortabilityViewTestCase):
    def test_redirects_with_slug_when_no_participant_in_session(self):
        self.client.session.flush()
        response = self.client.get(reverse("datadonation:tiktok_connection"))
        self.assertRedirects(
            response,
            reverse(
                "datadonation:portability_briefing",
                kwargs={"slug": settings.TIKTOK_DDM_PROJECT_SLUG},
            ),
        )

    def test_passes_through_with_valid_participant(self):
        response = self.client.get(reverse("datadonation:tiktok_connection"))
        self.assertEqual(response.status_code, 200)

    def test_redirects_when_participant_was_deleted(self):
        self.participant.delete()
        response = self.client.get(reverse("datadonation:tiktok_connection"))
        self.assertRedirects(
            response,
            reverse(
                "datadonation:portability_briefing",
                kwargs={"slug": settings.TIKTOK_DDM_PROJECT_SLUG},
            ),
        )


class ConnectionInSessionMixinTest(PortabilityViewTestCase):
    def test_redirects_with_slug_when_no_connection_in_session(self):
        response = self.client.get(reverse("datadonation:tiktok_await_data"))
        self.assertRedirects(
            response,
            reverse(
                "datadonation:portability_briefing",
                kwargs={"slug": settings.TIKTOK_DDM_PROJECT_SLUG},
            ),
        )

    def test_passes_through_with_valid_connection(self):
        connection = self._create_connection()
        self._seed_connection_session(connection)
        response = self.client.get(reverse("datadonation:tiktok_await_data"))
        self.assertEqual(response.status_code, 200)

    def test_redirects_when_connection_was_deleted(self):
        connection = self._create_connection()
        self._seed_connection_session(connection)
        connection.delete()
        response = self.client.get(reverse("datadonation:tiktok_await_data"))
        self.assertRedirects(
            response,
            reverse(
                "datadonation:portability_briefing",
                kwargs={"slug": settings.TIKTOK_DDM_PROJECT_SLUG},
            ),
        )


def _fake_token(open_id: str = "raw_open_id"):
    return {
        "open_id": open_id,
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "expires_in": 3600,
        "refresh_expires_in": 2592000,
        "token_type": "Bearer",
        "scope": "portability.activity.single",
    }


class TikTokCallbackViewTest(PortabilityViewTestCase):
    def _callback_url(self):
        return reverse("datadonation:tiktok_callback")

    @patch("ddcs.datadonation.portability.views.extract_request_id")
    @patch("ddcs.datadonation.portability.views.issue_data_request")
    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.oauth")
    def test_new_connection_stores_hashed_open_id_and_creates_data_request(
        self, mock_oauth, mock_get_valid_token, mock_issue, mock_extract
    ):
        mock_oauth.tiktok.authorize_access_token.return_value = _fake_token(
            "raw_open_id"
        )
        mock_get_valid_token.return_value = "access-token"
        mock_issue.return_value = {"request_id": 111}
        mock_extract.return_value = 111

        response = self.client.get(self._callback_url())

        self.assertRedirects(response, reverse("datadonation:tiktok_await_data"))
        connection = TikTokConnection.objects.get()
        self.assertEqual(connection.open_id, hash_open_id("raw_open_id"))
        self.assertNotEqual(connection.open_id, "raw_open_id")
        self.assertEqual(self.client.session["tiktok_connection_id"], connection.id)
        data_request = TikTokDataRequest.objects.get()
        self.assertEqual(data_request.connection, connection)
        self.assertEqual(data_request.request_id, 111)

    @patch("ddcs.datadonation.portability.views.extract_request_id")
    @patch("ddcs.datadonation.portability.views.issue_data_request")
    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.oauth")
    def test_invalid_scope_redirects(
        self, mock_oauth, mock_get_valid_token, mock_issue, mock_extract
    ):
        token_data = _fake_token("raw_open_id")
        token_data["scope"] = "invalid_scope"
        mock_oauth.tiktok.authorize_access_token.return_value = token_data
        mock_get_valid_token.return_value = "access-token"
        mock_issue.return_value = {"request_id": 111}
        mock_extract.return_value = 111

        response = self.client.get(self._callback_url())

        self.assertRedirects(response, reverse("datadonation:portability_exception"))

    @patch("ddcs.datadonation.portability.views.extract_request_id")
    @patch("ddcs.datadonation.portability.views.issue_data_request")
    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.oauth")
    def test_existing_connection_with_active_request_is_not_reissued(
        self, mock_oauth, mock_get_valid_token, mock_issue, mock_extract
    ):
        connection = self._create_connection("raw_open_id")
        TikTokDataRequest.objects.create(
            connection=connection,
            request_id=222,
            status=TikTokDataRequest.State.PENDING,
        )
        mock_oauth.tiktok.authorize_access_token.return_value = _fake_token(
            "raw_open_id"
        )

        response = self.client.get(self._callback_url())

        self.assertRedirects(response, reverse("datadonation:tiktok_await_data"))
        mock_issue.assert_not_called()
        self.assertEqual(TikTokDataRequest.objects.count(), 1)

    @patch("ddcs.datadonation.portability.views.extract_request_id")
    @patch("ddcs.datadonation.portability.views.issue_data_request")
    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.oauth")
    def test_existing_connection_with_only_inactive_requests_issues_new_one(
        self, mock_oauth, mock_get_valid_token, mock_issue, mock_extract
    ):
        connection = self._create_connection("raw_open_id")
        TikTokDataRequest.objects.create(
            connection=connection,
            request_id=333,
            status=TikTokDataRequest.State.EXPIRED,
        )
        mock_oauth.tiktok.authorize_access_token.return_value = _fake_token(
            "raw_open_id"
        )
        mock_get_valid_token.return_value = "access-token"
        mock_issue.return_value = {"request_id": 444}
        mock_extract.return_value = 444

        response = self.client.get(self._callback_url())

        self.assertRedirects(response, reverse("datadonation:tiktok_await_data"))
        mock_issue.assert_called_once()
        self.assertEqual(TikTokDataRequest.objects.count(), 2)

    @patch("ddcs.datadonation.portability.views.oauth")
    def test_oauth_error_redirects_to_exception_page(self, mock_oauth):
        mock_oauth.tiktok.authorize_access_token.side_effect = OAuthError(
            error="access_denied", description="user declined"
        )

        response = self.client.get(self._callback_url())

        self.assertRedirects(response, reverse("datadonation:portability_exception"))
        self.assertEqual(TikTokConnection.objects.count(), 0)

    @patch("ddcs.datadonation.portability.views.extract_request_id")
    @patch("ddcs.datadonation.portability.views.issue_data_request")
    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.oauth")
    def test_missing_request_id_redirects_to_exception_without_crashing(
        self, mock_oauth, mock_get_valid_token, mock_issue, mock_extract
    ):
        mock_oauth.tiktok.authorize_access_token.return_value = _fake_token(
            "raw_open_id"
        )
        mock_get_valid_token.return_value = "access-token"
        mock_issue.return_value = {"error": {"code": "invalid_scope"}}
        mock_extract.return_value = None

        response = self.client.get(self._callback_url())

        self.assertRedirects(response, reverse("datadonation:portability_exception"))
        self.assertEqual(TikTokDataRequest.objects.count(), 0)


class CheckDataAvailabilityViewTest(PortabilityViewTestCase):
    def setUp(self):
        super().setUp()
        self.connection = self._create_connection()
        self._seed_connection_session(self.connection)

    def _check_url(self):
        return reverse("datadonation:tiktok_check_request")

    def test_redirects_when_no_active_data_request(self):
        response = self.client.get(self._check_url())
        self.assertRedirects(response, reverse("datadonation:tiktok_connection"))

    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.poll_data_request_status")
    def test_pending_status_renders_pending_partial(
        self, mock_poll, mock_get_valid_token
    ):
        data_request = TikTokDataRequest.objects.create(
            connection=self.connection,
            request_id=555,
            status=TikTokDataRequest.State.NOT_POLLED,
        )
        mock_get_valid_token.return_value = "access-token"
        mock_poll.return_value = {"status": TikTokDataRequest.State.PENDING}

        response = self.client.get(self._check_url())

        self.assertContains(response, "TikTok-Daten verfügbar")
        template_names = [t.name for t in response.templates if t.name]
        self.assertIn(
            "datadonation/portability/partials/_data_download_pending_msg.html",
            template_names,
        )
        data_request.refresh_from_db()
        self.assertIsNotNone(data_request.last_polled)

    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.poll_data_request_status")
    def test_ready_status_renders_available_partial(
        self, mock_poll, mock_get_valid_token
    ):
        TikTokDataRequest.objects.create(
            connection=self.connection,
            request_id=556,
            status=TikTokDataRequest.State.NOT_POLLED,
        )
        mock_get_valid_token.return_value = "access-token"
        mock_poll.return_value = {"status": TikTokDataRequest.State.READY}

        response = self.client.get(self._check_url())

        template_names = [t.name for t in response.templates if t.name]
        self.assertIn(
            "datadonation/portability/partials/_data_download_available_msg.html",
            template_names,
        )

    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.poll_data_request_status")
    def test_expired_status_renders_expired_partial(
        self, mock_poll, mock_get_valid_token
    ):
        TikTokDataRequest.objects.create(
            connection=self.connection,
            request_id=557,
            status=TikTokDataRequest.State.NOT_POLLED,
        )
        mock_get_valid_token.return_value = "access-token"
        mock_poll.return_value = {"status": TikTokDataRequest.State.EXPIRED}

        response = self.client.get(self._check_url())

        template_names = [t.name for t in response.templates if t.name]
        self.assertIn(
            "datadonation/portability/partials/_data_download_expired_msg.html",
            template_names,
        )

    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.poll_data_request_status")
    def test_unrecognized_status_renders_error_partial(
        self, mock_poll, mock_get_valid_token
    ):
        TikTokDataRequest.objects.create(
            connection=self.connection,
            request_id=558,
            status=TikTokDataRequest.State.NOT_POLLED,
        )
        mock_get_valid_token.return_value = "access-token"
        mock_poll.return_value = {"status": "some_unrecognized_status"}

        response = self.client.get(self._check_url())

        template_names = [t.name for t in response.templates if t.name]
        self.assertIn(
            "datadonation/portability/partials/_data_download_error_msg.html",
            template_names,
        )

    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.poll_data_request_status")
    def test_poll_http_error_renders_error_partial_without_crashing(
        self, mock_poll, mock_get_valid_token
    ):
        TikTokDataRequest.objects.create(
            connection=self.connection,
            request_id=559,
            status=TikTokDataRequest.State.NOT_POLLED,
        )
        mock_get_valid_token.return_value = "access-token"
        mock_poll.side_effect = HTTPError("boom")

        response = self.client.get(self._check_url())

        self.assertEqual(response.status_code, 200)
        template_names = [t.name for t in response.templates if t.name]
        self.assertIn(
            "datadonation/portability/partials/_data_download_error_msg.html",
            template_names,
        )


class TikTokDownloadViewTest(PortabilityViewTestCase):
    def setUp(self):
        super().setUp()
        self.connection = self._create_connection()
        self._seed_connection_session(self.connection)
        self.data_request = TikTokDataRequest.objects.create(
            connection=self.connection,
            request_id=777,
            status=TikTokDataRequest.State.READY,
        )

    def _download_url(self):
        return reverse("datadonation:tiktok_download")

    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.download_data_request")
    def test_successful_download_streams_zip_and_marks_success(
        self, mock_download, mock_get_valid_token
    ):
        mock_get_valid_token.return_value = "access-token"
        fake_response = MagicMock()
        fake_response.iter_content.return_value = [b"chunk-1", b"chunk-2"]
        fake_response.headers = {"Content-Length": "14"}
        mock_download.return_value = fake_response

        response = self.client.post(self._download_url())

        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn(
            f'filename="tiktok_data_{self.data_request.request_id}.zip"',
            response["Content-Disposition"],
        )
        content = b"".join(response.streaming_content)
        self.assertEqual(content, b"chunk-1chunk-2")

        self.data_request.refresh_from_db()
        self.assertTrue(self.data_request.download_attempted)
        self.assertTrue(self.data_request.download_succeeded)
        self.assertIsNotNone(self.data_request.downloaded_at)

    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.download_data_request")
    def test_download_http_error_returns_502_without_marking_success(
        self, mock_download, mock_get_valid_token
    ):
        mock_get_valid_token.return_value = "access-token"
        mock_download.side_effect = HTTPError("boom")

        response = self.client.post(self._download_url())

        self.assertEqual(response.status_code, 502)
        self.data_request.refresh_from_db()
        self.assertFalse(self.data_request.download_succeeded)

    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.download_data_request")
    def test_mid_stream_failure_marks_attempted_but_not_succeeded(
        self, mock_download, mock_get_valid_token
    ):
        mock_get_valid_token.return_value = "access-token"

        def _raising_iter_content(chunk_size):
            yield b"chunk-1"
            msg = "connection dropped"
            raise ConnectionError(msg)

        fake_response = MagicMock()
        fake_response.iter_content.side_effect = _raising_iter_content
        fake_response.headers = {}
        mock_download.return_value = fake_response

        response = self.client.post(self._download_url())

        with self.assertRaises(ConnectionError):
            b"".join(response.streaming_content)

        self.data_request.refresh_from_db()
        self.assertTrue(self.data_request.download_attempted)
        self.assertFalse(self.data_request.download_succeeded)


class GetValidTokenTest(TestCase):
    def setUp(self):
        self.connection = TikTokConnection.objects.create(
            open_id="test_open_id",
            access_token="cached-access-token",
            refresh_token="cached-refresh-token",
            token_type="Bearer",
            scope="user.info.basic",
        )

    @patch("ddcs.datadonation.portability.services.requests.post")
    def test_returns_cached_token_without_http_call_when_not_expired(self, mock_post):
        self.connection.access_token_expires_at = timezone.now() + timedelta(hours=1)
        self.connection.save()

        token = get_valid_token(self.connection)

        self.assertEqual(token, "cached-access-token")
        mock_post.assert_not_called()

    @patch("ddcs.datadonation.portability.services.requests.post")
    def test_refreshes_and_persists_new_tokens_when_expired(self, mock_post):
        self.connection.access_token_expires_at = timezone.now() - timedelta(seconds=1)
        self.connection.save()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "refreshed-access-token",
            "refresh_token": "refreshed-refresh-token",
            "expires_in": 3600,
            "refresh_expires_in": 2592000,
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        token = get_valid_token(self.connection)

        self.assertEqual(token, "refreshed-access-token")
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.access_token, "refreshed-access-token")
        self.assertEqual(self.connection.refresh_token, "refreshed-refresh-token")
        self.assertIsNotNone(self.connection.access_token_expires_at)
        self.assertIsNotNone(self.connection.refresh_token_expires_at)


class PortabilityFlowIntegrationTest(PortabilityViewTestCase):
    """Walks the flow through Django's test client with only the TikTok-facing
    boundary (Authlib + services.py) mocked out; the ORM and session are real.
    """

    @patch("ddcs.datadonation.portability.views.extract_request_id")
    @patch("ddcs.datadonation.portability.views.issue_data_request")
    @patch("ddcs.datadonation.portability.views.get_valid_token")
    @patch("ddcs.datadonation.portability.views.poll_data_request_status")
    @patch("ddcs.datadonation.portability.views.download_data_request")
    @patch("ddcs.datadonation.portability.views.oauth")
    def test_full_flow_from_connection_page_to_download(  # noqa: PLR0913
        self,
        mock_oauth,
        mock_download,
        mock_poll,
        mock_get_valid_token,
        mock_issue,
        mock_extract,
    ):
        # Step 1: connection info page is reachable.
        response = self.client.get(reverse("datadonation:tiktok_connection"))
        self.assertEqual(response.status_code, 200)

        # Step 2: OAuth callback creates the connection and a data request.
        mock_oauth.tiktok.authorize_access_token.return_value = _fake_token(
            "raw_open_id"
        )
        mock_get_valid_token.return_value = "access-token"
        mock_issue.return_value = {"request_id": 999}
        mock_extract.return_value = 999

        response = self.client.get(reverse("datadonation:tiktok_callback"))
        self.assertRedirects(response, reverse("datadonation:tiktok_await_data"))
        connection = TikTokConnection.objects.get()
        self.assertEqual(self.client.session["tiktok_connection_id"], connection.id)
        data_request = TikTokDataRequest.objects.get()
        self.assertEqual(data_request.request_id, 999)

        # Step 3: await page renders (connection now present in session).
        response = self.client.get(reverse("datadonation:tiktok_await_data"))
        self.assertEqual(response.status_code, 200)

        # Step 4: polling reports the data is ready.
        mock_poll.return_value = {"status": TikTokDataRequest.State.READY}
        response = self.client.get(reverse("datadonation:tiktok_check_request"))
        template_names = [t.name for t in response.templates if t.name]
        self.assertIn(
            "datadonation/portability/partials/_data_download_available_msg.html",
            template_names,
        )

        # Step 5: download streams the ZIP and marks the request as downloaded.
        fake_download_response = MagicMock()
        fake_download_response.iter_content.return_value = [b"zip-bytes"]
        fake_download_response.headers = {}
        mock_download.return_value = fake_download_response

        response = self.client.post(reverse("datadonation:tiktok_download"))
        content = b"".join(response.streaming_content)
        self.assertEqual(content, b"zip-bytes")

        data_request.refresh_from_db()
        self.assertTrue(data_request.download_succeeded)
