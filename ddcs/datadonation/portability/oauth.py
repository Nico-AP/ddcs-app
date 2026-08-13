from authlib.integrations.django_client import OAuth
from django.conf import settings

from ddcs.datadonation.portability.endpoints import TIKTOK_AUTH_URL, TIKTOK_TOKEN_URL

oauth = OAuth()

oauth.register(
    name="tiktok",
    client_id=settings.TIKTOK_CLIENT_ID,
    client_secret=settings.TIKTOK_CLIENT_SECRET,
    authorize_url=TIKTOK_AUTH_URL,
    access_token_url=TIKTOK_TOKEN_URL,
    client_kwargs={
        "scope": (
            "user.info.basic,"
            "portability.postsandprofile.single,"
            "portability.directmessages.single,"
            "portability.activity.single"
        )
    },
    # TikTok expects client_key, not the standard client_id
    authorize_params={"client_key": settings.TIKTOK_CLIENT_ID},
    access_token_params={
        "grant_type": "authorization_code",
        "client_key": settings.TIKTOK_CLIENT_ID,
        "client_secret": settings.TIKTOK_CLIENT_SECRET,
    },
)
