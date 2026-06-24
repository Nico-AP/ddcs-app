from ddcs.core.types import TikTokUserData
from ddcs.metadata.models import DataOrigins, TikTokUser, TikTokVideo


# TODO: When scraper is introduced, add a specific scrape priority to the
#  entries created here.
# TODO: Make this task async/convert to celery task.
def register_donation_metadata(data: TikTokUserData) -> None:
    """Creates DB entries based on donation data.

    Handles watch history, followed accounts, and liked videos.
    """
    # Watch history
    if data.watch_history:
        videos_to_add = [
            TikTokVideo(id_tiktok=record["video_id"], added_by=DataOrigins.DONATION)
            for record in data.watch_history
        ]
        TikTokVideo.objects.bulk_create(videos_to_add, ignore_conflicts=True)

    # Liked videos
    if data.liked_videos:
        videos_to_add = [
            TikTokVideo(id_tiktok=record["video_id"], added_by=DataOrigins.DONATION)
            for record in data.liked_videos
        ]
        TikTokVideo.objects.bulk_create(videos_to_add, ignore_conflicts=True)

    # Followed accounts
    if data.followed_accounts:
        user_names = {record.get("username") for record in data.followed_accounts} - {
            None
        }
        users_to_add = [
            TikTokUser(name=user_name, added_by=DataOrigins.DONATION)
            for user_name in user_names
        ]
        TikTokUser.objects.bulk_create(users_to_add, ignore_conflicts=True)
