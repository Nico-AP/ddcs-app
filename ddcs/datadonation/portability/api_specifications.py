from enum import StrEnum

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"  # noqa: S105
TIKTOK_DATA_ADD_URL = "https://open.tiktokapis.com/v2/user/data/add/"
TIKTOK_DATA_CHECK_URL = "https://open.tiktokapis.com/v2/user/data/check/"
TIKTOK_DATA_DOWNLOAD_URL = "https://open.tiktokapis.com/v2/user/data/download/"


class Scopes(StrEnum):
    ACTIVITY = "portability.activity.single"
    POSTSANDPROFILE = "portability.postsandprofile.single"
    DIRECT_MESSAGES = "portability.directmessages.single"
    ALL = "portability.all.single"
