"""Which TOP Posters URL belongs to each piece of Kodi artwork.

Pure logic, no Kodi imports: the URLs mirror the ones the Jellyfin plugin
builds, and `reconcile` decides what to write back to the library.
"""

import re
from urllib.parse import quote, unquote

DEFAULT_BASE_URL = "https://api.top-posters.com"

# Kodi art type -> (API endpoint, file extension). Episode thumbnails have
# their own path shape and are handled apart.
ENDPOINTS = {
    "poster": ("poster", "jpg"),
    "landscape": ("banner", "jpg"),
    "fanart": ("background", "jpg"),
    "clearlogo": ("logo", "png"),
}

# The art types the add-on manages for each library item kind.
MANAGED_ART = {
    "movie": ("poster", "landscape", "fanart", "clearlogo"),
    "tvshow": ("poster", "landscape", "fanart", "clearlogo"),
    "season": ("poster",),
    "episode": ("thumb",),
}

_DIGITS = re.compile(r"^\d+$")
_IMDB = re.compile(r"^tt\d+$")


def unwrap(url):
    """Turn Kodi's `image://<encoded>/` form back into the plain URL."""
    if not url:
        return None
    if url.startswith("image://"):
        inner = url[len("image://"):]
        if inner.endswith("/"):
            inner = inner[:-1]
        return unquote(inner)
    return url


def is_remote(url):
    return bool(url) and url.startswith(("http://", "https://"))


def media_ref(kind, uniqueid):
    """(id_type, media_id) for a movie or a TV show, or None without usable IDs.

    TMDB comes first because it carries the media type and needs no lookup on
    the API side; IMDb and TVDB are resolved there.
    """
    uniqueid = uniqueid or {}
    tmdb = str(uniqueid.get("tmdb") or "")
    if _DIGITS.match(tmdb):
        return "tmdb", ("movie-" if kind == "movie" else "series-") + tmdb
    imdb = str(uniqueid.get("imdb") or "")
    if _IMDB.match(imdb):
        return "imdb", imdb
    tvdb = str(uniqueid.get("tvdb") or "")
    if kind != "movie" and _DIGITS.match(tvdb):
        return "tvdb", tvdb
    return None


class UrlBuilder(object):
    def __init__(self, base_url, api_key):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key

    def _url(self, id_type, tail, fallback):
        url = "%s/%s/%s/%s" % (self.base_url, quote(self.api_key, safe=""), id_type, tail)
        # The API answers any failure (unknown title, expired key, monthly
        # limit) with a redirect to fallback_url, so Kodi keeps showing the
        # original artwork instead of an empty slot.
        if is_remote(fallback):
            url += "?fallback_url=" + quote(fallback, safe="")
        return url

    def art(self, art_type, ref, fallback=None, season=None):
        endpoint, ext = ENDPOINTS[art_type]
        id_type, media_id = ref
        if season is not None:
            media_id = "%s-s%d" % (media_id, season)
        return self._url(id_type, "%s/%s.%s" % (endpoint, media_id, ext), fallback)

    def episode_thumb(self, ref, season, episode, fallback=None):
        id_type, media_id = ref
        return self._url(id_type, "thumbnail/%s/S%dE%d.jpg" % (media_id, season, episode), fallback)


def reconcile(art_types, current_art, saved, make_url, is_ours):
    """Changes to write so the item shows exactly the artwork it should.

    `current_art` holds unwrapped URLs. `saved` is this item's record of the
    original artwork and is updated in place: anything in the library that is
    not ours is, by definition, the current original (a rescrape replaces our
    URLs with fresh ones). `make_url(art_type, original)` returns our URL, or
    None when that art type should not be ours, in which case the original
    comes back. Returns {art_type: url or None}, None meaning "remove".
    """
    changes = {}
    for art_type in art_types:
        current = current_art.get(art_type)
        if current and is_ours(current):
            original = saved.get(art_type)
        else:
            original = current
            if original:
                saved[art_type] = original
            else:
                saved.pop(art_type, None)
        target = make_url(art_type, original) or original
        if target != current:
            changes[art_type] = target
    return changes
