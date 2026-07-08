from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict


class WatchHistoryRecord(TypedDict, total=False):
    date: datetime
    link: str
    video_id: int


class FollowedAccountRecord(TypedDict, total=False):
    date: datetime
    username: str


class LikedVideoRecord(TypedDict, total=False):
    date: datetime
    link: str
    video_id: int


@dataclass
class TikTokUserData:
    watch_history: list[WatchHistoryRecord] | None = None
    followed_accounts: list[FollowedAccountRecord] | None = None
    liked_videos: list[LikedVideoRecord] | None = None
    shared_videos: list[LikedVideoRecord] | None = None
    video_bookmarks: list[LikedVideoRecord] | None = None
    comments: list[LikedVideoRecord] | None = None
