from django.db import models
from wagtail import blocks
from wagtail.admin.panels import FieldPanel
from wagtail.contrib.settings.models import BaseSiteSetting
from wagtail.contrib.settings.registry import register_setting
from wagtail.fields import StreamField
from wagtail.models import Page


class UrlTargetChoiceBlock(blocks.ChoiceBlock):
    choices = [
        ("_blank", "New tab"),
        ("_self", "Same tab"),
    ]


class HeroBlock(blocks.StructBlock):
    anchor_id = blocks.CharBlock(
        required=False,
        help_text="Html ID used to link section "
        "(e.g. 'about' is accessible as: dfdw.de#about)",
        default="hero",
    )

    subtitle = blocks.CharBlock()
    intro = blocks.RichTextBlock()

    show_cta_button = blocks.BooleanBlock(required=False)
    cta_button_label = blocks.CharBlock(required=False)
    cta_button_link = blocks.URLBlock(required=False)

    show_secondary_link = blocks.BooleanBlock(required=False)
    secondary_link_label = blocks.CharBlock(required=False)
    secondary_link = blocks.URLBlock(required=False)
    secondary_link_target = UrlTargetChoiceBlock(default="_self")

    class Meta:
        template = "website/components/hero.html"
        icon = "pick"


class LogoBannerBlock(blocks.StructBlock):
    class Meta:
        template = "website/components/logo_banner.html"
        icon = "radio-full"


class SubtitleBlock(blocks.StructBlock):
    title = blocks.CharBlock(required=True)

    class Meta:
        template = "website/components/subtitle_block.html"
        icon = "title"


class ButtonBlock(blocks.StructBlock):
    label = blocks.CharBlock(required=True)
    link = blocks.URLBlock(required=True)
    link_target = UrlTargetChoiceBlock(default="_self")

    class Meta:
        template = "website/components/button_block.html"
        icon = "bold"


class SectionBlock(blocks.StructBlock):
    anchor_id = blocks.CharBlock(
        required=False,
        help_text=(
            "Html ID used to link section "
            "(e.g. 'about' is accessible as: dfdw.de#about)"
        ),
    )
    pre_title = blocks.CharBlock()
    title = blocks.CharBlock()

    body = blocks.StreamBlock(
        [
            ("richtext", blocks.RichTextBlock()),
            ("subtitle", SubtitleBlock()),
            ("button", ButtonBlock()),
        ],
        blank=True,
        use_json_field=True,
    )

    class Meta:
        template = "website/components/section.html"
        icon = "radio-full"


class ParticipationSectionBlock(blocks.StructBlock):
    anchor_id = blocks.CharBlock(
        required=False,
        help_text=(
            "Html ID used to link section "
            "(e.g. 'about' is accessible as: dfdw.de#about)"
        ),
        default="participation",
    )
    pre_title = blocks.CharBlock()
    title = blocks.CharBlock()
    content = blocks.RichTextBlock()

    step_1_title = blocks.CharBlock()
    step_1_content = blocks.RichTextBlock()

    step_2_title = blocks.CharBlock()
    step_2_content = blocks.RichTextBlock()

    step_3_title = blocks.CharBlock()
    step_3_content = blocks.RichTextBlock()

    class Meta:
        template = "website/components/participation_section.html"
        icon = "user"


class CardBlock(blocks.StructBlock):
    title = blocks.CharBlock()
    source_name = blocks.CharBlock()
    url = blocks.URLBlock()
    include_image = blocks.BooleanBlock(required=False)
    image_url = blocks.URLBlock(required=False)

    class Meta:
        template = "website/components/media_card.html"
        icon = "placeholder"


class CardSectionBlock(blocks.StructBlock):
    anchor_id = blocks.CharBlock(
        required=False,
        help_text=(
            "Html ID used to link section "
            "(e.g. 'about' is accessible as: dfdw.de#about)"
        ),
    )
    pre_title = blocks.CharBlock()
    title = blocks.CharBlock()
    cards = blocks.ListBlock(CardBlock())

    class Meta:
        template = "website/components/card_section.html"
        icon = "table"


class RegularPageBlock(blocks.StructBlock):
    pre_title = blocks.CharBlock()
    title = blocks.CharBlock()
    body = blocks.StreamBlock(
        [
            ("richtext", blocks.RichTextBlock()),
            ("subtitle", SubtitleBlock()),
            ("button", ButtonBlock()),
        ],
        blank=True,
        use_json_field=True,
    )

    class Meta:
        template = "website/components/content_page.html"
        icon = "radio-full"


class NavLinkBlock(blocks.StructBlock):
    label = blocks.CharBlock()
    page = blocks.PageChooserBlock(
        required=False,
        help_text="Takes precedence over URL if both are set",
    )
    url = blocks.URLBlock(
        required=False,
        help_text="Use this for links not accessible through 'page'",
    )
    anchor_id = blocks.CharBlock(
        required=False,
        help_text="Optional anchor on the target page, e.g. 'about' → page.url#about",
    )

    class Meta:
        icon = "link"


@register_setting
class NavigationSettings(BaseSiteSetting):
    nav_links = StreamField(
        [("link", NavLinkBlock())],
        blank=True,
        use_json_field=True,
        help_text="Links shown in the main navigation",
    )
    footer_pages = models.ManyToManyField(
        Page,
        blank=True,
        related_name="in_footer",
        help_text="Pages linked in the footer",
    )

    panels = [
        FieldPanel("nav_links"),
        FieldPanel("footer_pages"),
    ]

    class Meta:
        verbose_name = "Navigation Settings"


class PageNavAnchorBlock(blocks.StructBlock):
    anchor_id = blocks.CharBlock(
        help_text="Must match the anchor_id set on the target section block"
    )
    label = blocks.CharBlock()

    class Meta:
        icon = "link"


class SitePage(Page):
    template = "website/site_page.html"

    body = StreamField(
        [
            ("hero", HeroBlock()),
            ("section", SectionBlock()),
            ("participation_section", ParticipationSectionBlock()),
            ("card_section", CardSectionBlock()),
            ("logo_banner", LogoBannerBlock()),
            ("regular_page", RegularPageBlock()),
        ],
        blank=True,
        use_json_field=True,
    )

    nav_links = StreamField(
        [("link", NavLinkBlock())],
        blank=True,
        use_json_field=True,
        help_text="Links to other pages to include in the navigation",
    )

    nav_anchors = StreamField(
        [("anchor", PageNavAnchorBlock())],
        blank=True,
        use_json_field=True,
        help_text="Sections on this page to link in the navigation",
    )

    content_panels = [
        *Page.content_panels,
        FieldPanel("body"),
    ]

    promote_panels = [
        *Page.promote_panels,
        FieldPanel("nav_links"),
        FieldPanel("nav_anchors"),
    ]

    class Meta:
        verbose_name = "Site Page"

    def get_nav_anchors(self) -> list[dict]:
        return [
            {"id": block.value["anchor_id"], "label": block.value["label"]}
            for block in self.nav_anchors
        ]
