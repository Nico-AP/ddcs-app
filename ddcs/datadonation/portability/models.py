from datetime import timedelta

from django.db import models
from django.utils import timezone
from encrypted_fields import EncryptedTextField


class TikTokConnection(models.Model):
    open_id = models.CharField(max_length=255, unique=True)

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
    open_id = models.CharField(max_length=255)
    request_id = models.BigIntegerField(
        unique=True, help_text="ID of data request as provided by TikTok"
    )
    issued_at = models.DateTimeField(default=timezone.now)

    last_polled = models.DateTimeField(null=True)

    class State(models.TextChoices):
        NOT_POLLED = "not polled", "not polled"
        PENDING = "pending", "pending"
        READY = "downloading", "downloading"
        EXPIRED = "expired", "expired"
        CANCELLED = "cancelled", "cancelled"

    status = models.CharField(
        max_length=20,
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
        inactive_states = [self.State.EXPIRED, self.State.CANCELLED]
        return self.status not in inactive_states or self.download_succeeded
