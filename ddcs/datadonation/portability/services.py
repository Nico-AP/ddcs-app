import logging
from datetime import UTC, datetime

import requests
from django.conf import settings
from django.utils import timezone

from ddcs.datadonation.portability.endpoints import (
    TIKTOK_DATA_ADD_URL,
    TIKTOK_DATA_CHECK_URL,
    TIKTOK_DATA_DOWNLOAD_URL,
    TIKTOK_TOKEN_URL,
)
from ddcs.datadonation.portability.models import TikTokConnection

logger = logging.getLogger(__name__)


def get_valid_token(connection: TikTokConnection) -> str:
    if not connection.is_expired():
        return connection.access_token

    # Refresh the token
    response = requests.post(
        TIKTOK_TOKEN_URL,
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
        timezone.now().timestamp() + data["expires_in"], tz=UTC
    )
    connection.refresh_token_expires_at = datetime.fromtimestamp(
        timezone.now().timestamp() + data["refresh_expires_in"], tz=UTC
    )
    connection.save()

    return connection.access_token


def issue_data_request(access_token: str) -> dict:
    url = TIKTOK_DATA_ADD_URL
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    params = {"fields": "request_id"}
    payload = {"data_format": "json", "category_selection_list": ["all_data"]}

    response = requests.post(
        url, headers=headers, params=params, json=payload, timeout=(5, 30)
    )
    response.raise_for_status()
    return response.json()


def extract_request_id(data: dict) -> str | None:
    error_details = data.get("error", {})
    error_code = error_details.get("code") if isinstance(error_details, dict) else None
    if error_code and error_code != "ok":
        logger.warning("TikTok data request returned an error: %s", error_details)
        return None
    return data.get("request_id")


def poll_data_request_status(access_token: str, request_id: int) -> dict:
    url = TIKTOK_DATA_CHECK_URL
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    fields = [
        "request_id",
        "apply_time",
        "collect_time",
        "status",
        "data_format",
        "category_selection_list",
    ]
    params = {"fields": ",".join(fields)}
    payload = {
        "request_id": request_id,
    }
    response = requests.post(
        url, headers=headers, params=params, json=payload, timeout=30
    )
    response.raise_for_status()
    return response.json()


def download_data_request(access_token: str, request_id: int) -> requests.Response:
    url = TIKTOK_DATA_DOWNLOAD_URL
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    payload = {
        "request_id": request_id,
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        stream=True,
        timeout=(5, 15),
    )
    response.raise_for_status()
    return response
