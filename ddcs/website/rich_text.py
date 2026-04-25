from django.templatetags.static import static
from wagtail import hooks
from wagtail.admin.rich_text.converters.html_to_contentstate import (
    InlineStyleElementHandler,
)
from wagtail.admin.rich_text.editors.draftail.features import InlineStyleFeature


@hooks.register("insert_editor_css")
def editor_css() -> str:
    return f'<link rel="stylesheet" href="{static("core/css/ddcs.css")}">'


@hooks.register("register_rich_text_features")
def register_subtletitle_feature(features) -> None:  # noqa: ANN001
    """Adds a class 'subtle-title' to richtext-editor in wagtail."""

    feature_name = "subtle-title"
    type_ = "SUBTLETITLE"

    # 1. Define the Draftail config (the toolbar button)
    control = {
        "type": type_,
        "label": "ST",
        "description": "Subtle Title",
        "style": {
            "color": "#888",
            "fontWeight": "600",
            "letterSpacing": "0.05em",
            "padding-top": "10px",
        },
    }

    features.register_editor_plugin(
        "draftail", feature_name, InlineStyleFeature(control)
    )

    # 2. Define conversion from Draftail → HTML and back
    db_conversion = {
        "from_database_format": {
            'span[class="subtle-title"]': InlineStyleElementHandler(type_)
        },
        "to_database_format": {"style_map": {type_: 'span class="subtle-title"'}},
    }

    features.register_converter_rule("contentstate", feature_name, db_conversion)
