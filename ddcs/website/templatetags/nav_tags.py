from django import template

from ddcs.website.models import NavigationSettings

register = template.Library()


@register.simple_tag(takes_context=True)
def get_navigation(context: dict) -> dict[str, list]:
    """Gathers all navigation menu items from wagtail."""

    request = context["request"]
    page = context.get("page")

    nav = NavigationSettings.for_request(request)

    nav_links = []

    # Global links from NavigationSettings
    for block in nav.nav_links if nav else []:
        link = block.value
        if link.get("page"):
            nav_links.append(
                {
                    "label": link["label"],
                    "url": link["page"].url
                    + (f"#{link['anchor_id']}" if link.get("anchor_id") else ""),
                }
            )

    # Per-page links
    if page and hasattr(page, "nav_links"):
        for block in page.nav_links if nav else []:
            link = block.value
            if link.get("page"):
                nav_links.append(
                    {
                        "label": link["label"],
                        "url": link["page"].url
                        + (f"#{link['anchor_id']}" if link.get("anchor_id") else ""),
                    }
                )
            elif link.get("url"):
                nav_links.append(
                    {
                        "label": link["label"],
                        "url": link["url"],
                    }
                )

    # Per-page anchors
    nav_anchors = []
    if page and hasattr(page, "get_nav_anchors"):
        nav_anchors.extend(
            {"label": anchor["label"], "url": f"#{anchor['id']}"}
            for anchor in page.get_nav_anchors()
        )

    return {
        "nav_links": nav_links,
        "nav_anchors": nav_anchors,
        "footer_pages": nav.footer_pages.live().specific() if nav else [],
    }
