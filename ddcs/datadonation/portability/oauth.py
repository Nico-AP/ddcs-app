from authlib.integrations.django_client import OAuth
from django.conf import settings

TT_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize"
TT_ACCESS_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"  # noqa: S105

oauth = OAuth()

oauth.register(
    name="tiktok",
    client_id=settings.TIKTOK_CLIENT_ID,
    client_secret=settings.TIKTOK_CLIENT_SECRET,
    authorize_url=TT_AUTH_URL,
    access_token_url=TT_ACCESS_TOKEN_URL,
    client_kwargs={"scope": "user.info.basic"},
    # TikTok expects client_key, not the standard client_id
    authorize_params={"client_key": settings.TIKTOK_CLIENT_ID},
)
