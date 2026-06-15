"""Per-page artwork for the section-landing heroes.

The old LSP site set each page's title over a piece of artwork. We carry that
forward on the new site's *section landings* (not on detail/list children or
utility pages). Artwork is mapped here in code (a dev edit + deploy changes it),
keyed by the namespaced URL/view name (``request.resolver_match.view_name``).

Image paths are relative to a static dir (resolved with ``{% static %}`` in the
hero partial). Pages with no entry render an image-less header — the hero
degrades gracefully, so a landing can ship before its artwork is chosen.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Artwork:
    """One banner image plus its attribution.

    ``focal`` is any CSS ``background-position`` value (e.g. ``"center"``,
    ``"50% 30%"``) so we can keep the meaningful part of an off-center work in
    view as the band crops on narrow screens.
    """

    image: str
    artist: str = ""
    title: str = ""
    focal: str = "center"


# Keyed by namespaced view name (``request.resolver_match.view_name``). Add an
# entry once its image lives under ``static/img/artwork/``; until then the page
# shows an image-less hero header.
#
# Images carried over from the old Wix site (see task #259). For pages that had
# a direct old equivalent (About, Program, Events, Find-an-Analyst) the banner
# is the one the school actually showed; new-only pages (Groups, Guides,
# Calendar, Parlêtre, …) reuse quieter library/architecture images. ``artist``
# holds the only attribution we have — blank where the artist is unknown. Many
# works are likely under copyright; see the ``image-rights`` note (task #259).
# This map is the one place to swap, recrop (``focal``), or clear any banner.
PAGE_ARTWORK: dict[str, Artwork] = {
    "about": Artwork("img/artwork/about.jpg", artist="Paul Klee"),
    "the_school": Artwork("img/artwork/the-school.jpg", artist="Wassily Kandinsky"),
    "program": Artwork("img/artwork/program.jpg"),
    "events:list": Artwork("img/artwork/events.jpg"),
    "directory": Artwork("img/artwork/directory.jpg"),
    "works:index": Artwork("img/artwork/works.jpg", artist="Louise Nevelson", title="Cascade VII"),
    "documents:index": Artwork("img/artwork/documents.jpg"),
    "core:calendar": Artwork("img/artwork/calendar.jpg", artist="George Peabody Library"),
    "workgroups:list": Artwork("img/artwork/groups.jpg", artist="Bibliothèque Mazarine, Paris"),
    "guides_index": Artwork("img/artwork/guides.jpg", artist="Beinecke Library, Yale"),
    "parletre:index": Artwork(
        "img/artwork/parletre.jpg", artist="Bibliothèque Sainte-Geneviève, Paris"
    ),
}


def for_view(view_name: str | None) -> Artwork | None:
    """Return the Artwork mapped to ``view_name``, or None if unmapped."""
    if not view_name:
        return None
    return PAGE_ARTWORK.get(view_name)
