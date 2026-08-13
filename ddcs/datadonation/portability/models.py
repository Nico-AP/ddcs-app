from datetime import timedelta

from django.db import models
from django.utils import timezone
from encrypted_fields import EncryptedTextField


class TikTokConnection(models.Model):
    open_id = models.CharField(max_length=255, unique=True)  # stores HMAC hash

    access_token = EncryptedTextField(max_length=255)
    access_token_expires_at = models.DateTimeField(null=True)

    refresh_token = EncryptedTextField(max_length=255)
    refresh_token_expires_at = models.DateTimeField(null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    token_type = models.CharField(max_length=255)  # usually "Bearer"
    scope = models.CharField(max_length=255)  # Comma separated list of scopes

    def __str__(self) -> str:
        return f"TikTok Connection {self.pk}"

    def is_expired(self, threshold: int = 0) -> bool:
        """Check if token is expired or expiring soon.

        Args:
            threshold: Time in seconds before actual expiration to consider
                token expired.

        Returns:
            bool: True if token is expired (or expiring soon)
        """
        if not self.access_token_expires_at:
            return True
        expiration_time = self.access_token_expires_at - timedelta(seconds=threshold)
        return timezone.now() > expiration_time

    def refresh_is_expired(self, threshold: int = 0) -> bool:
        """Check if refresh token is expired or expiring soon.

        Args:
            threshold: Time in seconds before actual expiration to consider
                token expired.

        Returns:
            bool: True if token is expired (or expiring soon)
        """
        if not self.refresh_token_expires_at:
            return True
        expiration_time = self.refresh_token_expires_at - timedelta(seconds=threshold)
        return timezone.now() > expiration_time

    def get_scope_list(self) -> list:
        return self.scope.split(",")


class TikTokDataRequest(models.Model):
    connection = models.ForeignKey(
        TikTokConnection,
        on_delete=models.SET_NULL,
        null=True,
        related_name="data_requests",
    )
    request_id = models.BigIntegerField(
        unique=True, help_text="ID of data request as provided by TikTok"
    )
    issued_at = models.DateTimeField(default=timezone.now)

    last_polled = models.DateTimeField(null=True)

    class State(models.TextChoices):
        """These are the official status strings returned by the TikTok API.

        DOWNLOADED was added for completion, not part of the API schema.
        """

        NOT_POLLED = "not polled", "not polled"
        PENDING = "pending", "pending"
        READY = "downloading", "ready to download"
        DOWNLOADED = "downloaded", "downloaded"
        EXPIRED = "expired", "expired"
        CANCELLED = "cancelled", "cancelled"

    ACTIVE_STATES = [State.NOT_POLLED, State.PENDING, State.READY]

    status = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.NOT_POLLED,
    )

    download_attempted = models.BooleanField(default=False)
    download_succeeded = models.BooleanField(default=False)
    downloaded_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self) -> str:
        return f"TikTok Data Request {self.request_id}"

    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATES
