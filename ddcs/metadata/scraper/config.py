MAIN_URL = "https://www.tiktok.com"

BASE_URLS = {
    "video": "https://www.tiktok.com/@tiktok/video/{id}",
    "user": "https://www.tiktok.com/@{username}",
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

RATE_LIMIT_DELAY = 1.0

# (connect, read) timeouts in seconds.
REQUEST_TIMEOUT = (5, 20)

# HTTP statuses TikTok answers with when it refuses to serve us.
BLOCKED_STATUS_CODES = frozenset({403, 429})
