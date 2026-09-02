from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from redis.exceptions import ConnectionError as RedisConnectionError

from ddcs.metadata.research_api.credentials import (
    _EXHAUSTION_KEY_PREFIX,
    get_research_api_credentials,
    is_credentials_exhausted,
    mark_credentials_exhausted,
    seconds_until_next_utc_midnight,
)


@override_settings(
    TIKTOK_RESEARCH_API_KEY="pk",
    TIKTOK_RESEARCH_API_SECRET="ps",
    TIKTOK_RESEARCH_API_KEY_SECONDARY="",
    TIKTOK_RESEARCH_API_SECRET_SECONDARY="",
)
class GetResearchAPICredentialsTests(SimpleTestCase):
    def test_primary_only(self):
        self.assertEqual(get_research_api_credentials(), [("pk", "ps")])

    @override_settings(
        TIKTOK_RESEARCH_API_KEY_SECONDARY="sk",
        TIKTOK_RESEARCH_API_SECRET_SECONDARY="ss",
    )
    def test_both_pairs_in_order(self):
        self.assertEqual(get_research_api_credentials(), [("pk", "ps"), ("sk", "ss")])

    @override_settings(TIKTOK_RESEARCH_API_KEY_SECONDARY="sk")
    def test_half_configured_secondary_dropped(self):
        self.assertEqual(get_research_api_credentials(), [("pk", "ps")])

    @override_settings(TIKTOK_RESEARCH_API_KEY="", TIKTOK_RESEARCH_API_SECRET="")
    def test_nothing_configured(self):
        self.assertEqual(get_research_api_credentials(), [])


class SecondsUntilNextUTCMidnightTests(SimpleTestCase):
    def test_one_hour_before_midnight(self):
        now = datetime(2026, 9, 2, 23, 0, tzinfo=UTC)
        self.assertEqual(seconds_until_next_utc_midnight(now), 3600)

    def test_exact_midnight_is_full_day(self):
        now = datetime(2026, 9, 2, 0, 0, tzinfo=UTC)
        self.assertEqual(seconds_until_next_utc_midnight(now), 86400)

    def test_always_positive(self):
        now = datetime(2026, 9, 2, 23, 59, 59, 999999, tzinfo=UTC)
        self.assertGreaterEqual(seconds_until_next_utc_midnight(now), 1)


class ExhaustionHintTests(SimpleTestCase):
    def test_mark_sets_key_with_ttl(self):
        fake = MagicMock()

        mark_credentials_exhausted(1, client=fake)

        fake.set.assert_called_once()
        args, kwargs = fake.set.call_args
        self.assertEqual(args[0], f"{_EXHAUSTION_KEY_PREFIX}1")
        self.assertEqual(args[1], b"1")
        self.assertIsInstance(kwargs["ex"], int)
        self.assertGreater(kwargs["ex"], 0)

    def test_is_exhausted_maps_truthiness(self):
        fake = MagicMock()
        fake.exists.return_value = 1
        self.assertTrue(is_credentials_exhausted(0, client=fake))
        fake.exists.return_value = 0
        self.assertFalse(is_credentials_exhausted(0, client=fake))

    def test_mark_swallows_redis_errors(self):
        fake = MagicMock()
        fake.set.side_effect = RedisConnectionError("down")

        with self.assertLogs("ddcs.metadata.research_api.credentials", level="WARNING"):
            self.assertIsNone(mark_credentials_exhausted(0, client=fake))

    def test_is_exhausted_returns_false_on_redis_error(self):
        fake = MagicMock()
        fake.exists.side_effect = RedisConnectionError("down")

        with self.assertLogs("ddcs.metadata.research_api.credentials", level="WARNING"):
            self.assertFalse(is_credentials_exhausted(0, client=fake))

    @override_settings(CELERY_BROKER_URL="redis://example:6379/0")
    @patch("ddcs.metadata.research_api.credentials.Redis")
    def test_default_client_uses_broker_url(self, redis_cls):
        mark_credentials_exhausted(0)
        redis_cls.from_url.assert_called_once_with("redis://example:6379/0")
