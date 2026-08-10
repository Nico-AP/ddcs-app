from ddcs.metadata.models import Keyword, TikTokVideo
from ddcs.metadata.research_api.utils.keyword_matching import find_matching_keywords


def backfill_keywords(
    keywords: list[Keyword] | None = None, batch_size: int = 2000
) -> int:
    """Retroactively link existing TikTokVideos to keywords via `find_matching_keywords`

    Needed because keyword matching only runs at sync time (`_sync_keywords`),
    so a keyword added or re-enabled after a video was synced never gets
    evaluated against that video. Call this after `monitor_api=True` changes
    on `Keyword` rows to fill that gap — see `sync_monitored_items`, which
    calls it automatically for newly-created and newly-reenabled keywords.

    Matches against each video's description and hashtags (reusing the same
    logic as live sync) and writes new keyword-video links directly to the
    M2M through table in batches, skipping the ORM's per-video `.add()` to
    avoid a query per link. Safe to re-run: already-linked pairs are skipped
    via `ignore_conflicts=True`, so re-running after a partial failure or on
    an unchanged keyword set is a no-op.

    Args:
        keywords: Keywords to match against all videos. Defaults to every
            `Keyword` with `monitor_api=True`.
        batch_size: Number of through-table rows to buffer before each
            `bulk_create`.

    Returns:
        Number of new keyword-video links created (not the number of videos
        touched — one video matching two keywords counts as 2).
    """
    if keywords is None:
        keywords = list(Keyword.objects.filter(monitor_api=True))
    if not keywords:
        return 0

    ThroughModel = TikTokVideo.keywords.through  # noqa: N806
    videos = TikTokVideo.objects.prefetch_related("api_infos", "hashtags")

    def _flush(batch: list) -> int:
        before = ThroughModel.objects.count()
        ThroughModel.objects.bulk_create(batch, ignore_conflicts=True)
        after = ThroughModel.objects.count()
        return after - before

    to_create = []
    total_created = 0
    for video in videos:
        video_info = video.api_infos.first()
        matched = find_matching_keywords(
            keywords,
            description=getattr(video_info, "description", ""),
            hashtag_names=[h.name for h in video.hashtags.all()],
        )

        to_create.extend(
            [ThroughModel(tiktokvideo_id=video.id, keyword_id=kw.id) for kw in matched]
        )

        if len(to_create) >= batch_size:
            total_created += _flush(to_create)
            to_create.clear()

    if to_create:
        total_created += _flush(to_create)

    return total_created
