import logging

from ddm.datadonation.models import DonationBlueprint, FileUploader, ProcessingRule
from ddm.projects.models import DonationProject, ResearchProfile
from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError, CommandParser

from ddcs.datadonation.config import (
    DDM_TIKTOK_PROJECT_SLUG,
    FOLLOWED_BP_NAME,
    LIKED_VIDEOS_BP_NAME,
    WATCH_HISTORY_BP_NAME,
)

logger = logging.getLogger(__name__)

User = get_user_model()


PROJECT_CONFIG = {
    "name": "TikTok",
    "contact_information": "",
    "data_protection_statement": "",
    "slug": DDM_TIKTOK_PROJECT_SLUG,
    "briefing_text": "",
    "briefing_consent_enabled": False,
    "briefing_consent_label_yes": "Ja",
    "briefing_consent_label_no": "Nein",
    "debriefing_text": "",
    "super_secret": False,
    "redirect_enabled": False,
    "redirect_target": "",
    "url_parameter_enabled": True,
    "expected_url_parameters": "class",
    "active": True,
}

FILE_UPLOADER_CONFIG = {
    "name": "TikTok",
    "upload_type": "zip file",
    "combined_consent": False,
}

BLUEPRINT_CONFIGS = [
    {
        "name": WATCH_HISTORY_BP_NAME,
        "display_name": "Angesehene Videos",
        "description": "Videos, die du dir angesehen hast.",
        "display_position": 1,
        "exp_file_format": "json",
        "json_extraction_root": "Your Activity.Watch History.VideoList",
        "csv_delimiter": "",
        "expected_fields": '"Date", "Link"',
        "expected_fields_regex_matching": False,
        "regex_path": "user_data_tiktok\\.json",
        "processing_rules": [
            {
                "name": "Keep Date",
                "field": "Date",
                "regex_field": False,
                "execution_order": 1,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep Link",
                "field": "Link",
                "regex_field": False,
                "execution_order": 2,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
        ],
    },
    {
        "name": "posted_videos",
        "display_name": "Gepostete Videos",
        "description": "Informationen, wann und mit welchen Einstellungen du "
        "Videos gepostet hast. Der Link und der Titel des Videos "
        "wird nicht ausgelesen.",
        "display_position": 2,
        "exp_file_format": "json",
        "json_extraction_root": "Post.Posts.VideoList",
        "csv_delimiter": "",
        "expected_fields": '"Date", "Link"',
        "expected_fields_regex_matching": False,
        "regex_path": "user_data_tiktok\\.json",
        "processing_rules": [
            {
                "name": "Keep Date",
                "field": "Date",
                "regex_field": False,
                "execution_order": 1,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep WhoCanView",
                "field": "WhoCanView",
                "regex_field": False,
                "execution_order": 2,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep AllowComments",
                "field": "AllowComments",
                "regex_field": False,
                "execution_order": 3,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep AllowStitches",
                "field": "AllowStitches",
                "regex_field": False,
                "execution_order": 4,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep AllowDuets",
                "field": "AllowDuets",
                "regex_field": False,
                "execution_order": 5,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep AllowSharingToStory",
                "field": "AllowSharingToStory",
                "regex_field": False,
                "execution_order": 6,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep ContentDisclosure",
                "field": "ContentDisclosure",
                "regex_field": False,
                "execution_order": 7,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep AIGeneratedContent",
                "field": "AIGeneratedContent",
                "regex_field": False,
                "execution_order": 8,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep Sound",
                "field": "Sound",
                "regex_field": False,
                "execution_order": 9,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
        ],
    },
    {
        "name": "activity_summary",
        "display_name": "Aktivitätszusammenfassung",
        "description": "Anzahl der Videos, die du kommentiert, geteilt und "
        "angesehen hast.",
        "display_position": 3,
        "exp_file_format": "json",
        "json_extraction_root": "Your Activity.Activity Summary.ActivitySummaryMap",
        "csv_delimiter": "",
        "expected_fields": '"videosWatchedToTheEndSinceAccountRegistration"',
        "expected_fields_regex_matching": False,
        "regex_path": "user_data_tiktok\\.json",
        "processing_rules": [
            {
                "name": "Keep videosCommentedOnSinceAccountRegistration",
                "field": "videosCommentedOnSinceAccountRegistration",
                "regex_field": False,
                "execution_order": 1,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep videosSharedSinceAccountRegistration",
                "field": "videosSharedSinceAccountRegistration",
                "regex_field": False,
                "execution_order": 2,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep videosWatchedToTheEndSinceAccountRegistration",
                "field": "videosWatchedToTheEndSinceAccountRegistration",
                "regex_field": False,
                "execution_order": 3,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
        ],
    },
    {
        "name": "effect_bookmarks",
        "display_name": "Effekt-Bookmarks",
        "description": "Effekte, die du gespeichert hast.",
        "display_position": 4,
        "exp_file_format": "json",
        "json_extraction_root": "Your Activity.Favorite Effects.FavoriteEffectsList",
        "csv_delimiter": "",
        "expected_fields": '"EffectLink"',
        "expected_fields_regex_matching": False,
        "regex_path": "user_data_tiktok\\.json",
        "processing_rules": [
            {
                "name": "Keep Date",
                "field": "Date",
                "regex_field": False,
                "execution_order": 1,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep EffectLink",
                "field": "EffectLink",
                "regex_field": False,
                "execution_order": 2,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
        ],
    },
    {
        "name": "hashtag_bookmarks",
        "display_name": "Hashtag-Bookmarks",
        "description": "Hashtags, die du gespeichert hast.",
        "display_position": 5,
        "exp_file_format": "json",
        "json_extraction_root": "Your Activity.Favorite Hashtags.FavoriteHashtagList",
        "csv_delimiter": "",
        "expected_fields": '"Date"',
        "expected_fields_regex_matching": False,
        "regex_path": "user_data_tiktok\\.json",
        "processing_rules": [
            {
                "name": "Keep Date",
                "field": "Date",
                "regex_field": False,
                "execution_order": 1,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep Link",
                "field": "(L|l)ink",
                "regex_field": True,
                "execution_order": 2,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
        ],
    },
    {
        "name": "video_bookmarks",
        "display_name": "Video-Bookmarks",
        "description": "Videos, die du gespeichert hast.",
        "display_position": 6,
        "exp_file_format": "json",
        "json_extraction_root": "Your Activity.Favorite Videos.FavoriteVideoList",
        "csv_delimiter": "",
        "expected_fields": '"Date"',
        "expected_fields_regex_matching": False,
        "regex_path": "user_data_tiktok\\.json",
        "processing_rules": [
            {
                "name": "Keep Date",
                "field": "Date",
                "regex_field": False,
                "execution_order": 1,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep Link",
                "field": "(L|l)ink",
                "regex_field": True,
                "execution_order": 2,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
        ],
    },
    {
        "name": "sound_bookmarks",
        "display_name": "Sound-Bookmarks",
        "description": "Sounds, die du gespeichert hast.",
        "display_position": 7,
        "exp_file_format": "json",
        "json_extraction_root": "Your Activity.Favorite Sounds.FavoriteSoundList",
        "csv_delimiter": "",
        "expected_fields": '"Date"',
        "expected_fields_regex_matching": False,
        "regex_path": "user_data_tiktok\\.json",
        "processing_rules": [
            {
                "name": "Keep Date",
                "field": "Date",
                "regex_field": False,
                "execution_order": 1,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep Link",
                "field": "(L|l)ink",
                "regex_field": True,
                "execution_order": 2,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
        ],
    },
    {
        "name": FOLLOWED_BP_NAME,
        "display_name": "Gefolgte Accounts",
        "description": "Accounts, denen du folgst.",
        "display_position": 8,
        "exp_file_format": "json",
        "json_extraction_root": "Your Activity.Following.Following",
        "csv_delimiter": "",
        "expected_fields": '"Date", "UserName"',
        "expected_fields_regex_matching": False,
        "regex_path": "user_data_tiktok\\.json",
        "processing_rules": [
            {
                "name": "Keep Date",
                "field": "Date",
                "regex_field": False,
                "execution_order": 1,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep UserName",
                "field": "UserName",
                "regex_field": False,
                "execution_order": 2,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
        ],
    },
    {
        "name": LIKED_VIDEOS_BP_NAME,
        "display_name": "Gelikte Videos",
        "description": "Videos, die du geliked hast.",
        "display_position": 9,
        "exp_file_format": "json",
        "json_extraction_root": "Your Activity.Like List.ItemFavoriteList",
        "csv_delimiter": "",
        "expected_fields": '"(D|d)ate"',
        "expected_fields_regex_matching": True,
        "regex_path": "user_data_tiktok\\.json",
        "processing_rules": [
            {
                "name": "Keep date",
                "field": "(D|d)ate",
                "regex_field": True,
                "execution_order": 1,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep Link",
                "field": "(L|l)ink",
                "regex_field": True,
                "execution_order": 2,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
        ],
    },
    {
        "name": "searches",
        "display_name": "Durchgeführte Suchen",
        "description": "Die Begriffe, nach denen du gesucht hast.",
        "display_position": 10,
        "exp_file_format": "json",
        "json_extraction_root": "Your Activity.Searches.SearchList",
        "csv_delimiter": "",
        "expected_fields": '"Date"',
        "expected_fields_regex_matching": False,
        "regex_path": "user_data_tiktok\\.json",
        "processing_rules": [
            {
                "name": "Keep Date",
                "field": "Date",
                "regex_field": False,
                "execution_order": 1,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep SearchTerm",
                "field": "SearchTerm",
                "regex_field": False,
                "execution_order": 2,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
        ],
    },
    {
        "name": "comments",
        "display_name": "Kommentare (nur Zeitpunkt)",
        "description": "Zeitpunkte, an denen du einen Kommentar hinterlassen "
        "hast. Der Inhalt der Kommentare wird nicht ausgelesen.",
        "display_position": 11,
        "exp_file_format": "json",
        "json_extraction_root": "Comment.Comments.CommentsList",
        "csv_delimiter": "",
        "expected_fields": '"comment"',
        "expected_fields_regex_matching": False,
        "regex_path": "user_data_tiktok\\.json",
        "processing_rules": [
            {
                "name": "Keep date",
                "field": "(D|d)ate",
                "regex_field": True,
                "execution_order": 1,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
        ],
    },
    {
        "name": "shared_videos",
        "display_name": "Geteilte Videos",
        "description": "Informationen zu den Videos, die du mit anderen geteilt hast.",
        "display_position": 12,
        "exp_file_format": "json",
        "json_extraction_root": "Your Activity.Share History.ShareHistoryList",
        "csv_delimiter": "",
        "expected_fields": '"Date", "SharedContent"',
        "expected_fields_regex_matching": False,
        "regex_path": "user_data_tiktok\\.json",
        "processing_rules": [
            {
                "name": "Keep Date",
                "field": "Date",
                "regex_field": False,
                "execution_order": 1,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep SharedContent",
                "field": "SharedContent",
                "regex_field": False,
                "execution_order": 2,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep Method",
                "field": "Method",
                "regex_field": False,
                "execution_order": 3,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
            {
                "name": "Keep Link",
                "field": "(L|l)ink",
                "regex_field": True,
                "execution_order": 4,
                "comparison_operator": None,
                "comparison_value": "",
                "replacement_value": "",
            },
        ],
    },
]


class Command(BaseCommand):
    help = "Creates a DDM project to collect TikTok donations. "

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("user_id", type=int)

    def handle(self, *args, **options) -> str | None:
        user_id = options["user_id"]

        # Try to get user
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist as e:
            msg = f"User with ID {user_id} not found"
            raise CommandError(msg) from e

        # Check if project already exists
        if DonationProject.objects.filter(slug=DDM_TIKTOK_PROJECT_SLUG).exists():
            msg = f"DDM project with URL ID '{DDM_TIKTOK_PROJECT_SLUG}' already exists"
            self.stdout.write(self.style.NOTICE(msg))
            return

        # Get or create research profile
        owner_profile, _ = ResearchProfile.objects.get_or_create(user=user)

        # Create Project
        project = DonationProject.objects.create(
            owner=owner_profile,
            **PROJECT_CONFIG,
        )

        # Create Uploader
        uploader = FileUploader.objects.create(
            project=project,
            **FILE_UPLOADER_CONFIG,
        )

        # Create Blueprints
        for config in BLUEPRINT_CONFIGS:
            bp_config = {i: config[i] for i in config if i != "processing_rules"}
            blueprint = DonationBlueprint.objects.create(
                project=project,
                file_uploader=uploader,
                **bp_config,
            )

            # Create processing rules
            for rule in config["processing_rules"]:
                ProcessingRule.objects.create(
                    blueprint=blueprint,
                    **rule,
                )

        msg = (
            f"DDM project with URL ID '{DDM_TIKTOK_PROJECT_SLUG}' successfully created"
        )

        self.stdout.write(self.style.SUCCESS(msg))
