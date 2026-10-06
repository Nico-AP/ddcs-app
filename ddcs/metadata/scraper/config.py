from datetime import date

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

# Only videos a donor watched within this period (both days inclusive, UTC)
# are queued for scraping. Same period as the public report
# (ddcs.reports.config.PUBLIC_POST_DATA_*), defined separately because the
# reports app depends on this one, not the other way round.
WATCH_WINDOW_START = date(2026, 7, 1)
WATCH_WINDOW_END = date(2026, 9, 20)

# Queue order (see ``ScraperService._select_targets``): videos watched by at
# least ``PRIORITY_MIN_OCCURRENCES`` donations, with a view on or after
# ``PRIORITY_WATCHED_SINCE`` (UTC), are scraped first, most donations first.
# Everything else follows by most recent view.
PRIORITY_MIN_OCCURRENCES = 15
PRIORITY_WATCHED_SINCE = date(2026, 8, 1)
