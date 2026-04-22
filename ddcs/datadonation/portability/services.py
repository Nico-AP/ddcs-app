from datetime import datetime

import requests
from django.conf import settings
from django.utils import timezone

from ddcs.datadonation.portability.models import TikTokConnection


def get_valid_token(connection: TikTokConnection) -> str:
    if not connection.is_expired():
        return connection.access_token

    # Refresh the token
    response = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        data={
            "grant_type": "refresh_token",
            "client_key": settings.TIKTOK_CLIENT_ID,
            "client_secret": settings.TIKTOK_CLIENT_SECRET,
            "refresh_token": connection.refresh_token,
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    connection.access_token = data["access_token"]
    connection.refresh_token = data.get("refresh_token", connection.refresh_token)
    connection.access_token_expires_at = datetime.fromtimestamp(
        timezone.now().timestamp() + data["expires_in"], tz=timezone.utc
    )
    # TODO: Also read refresh expiration
    connection.save()

    return connection.access_token
