from urllib.parse import parse_qs, urlparse

from resources.lib.artwork import UrlBuilder, media_ref, reconcile, unwrap

from fakekodi import wrap

BASE = "https://api.top-posters.com"


def test_media_ref_prefers_tmdb_then_imdb_then_tvdb():
    assert media_ref("movie", {"tmdb": "603", "imdb": "tt0133093"}) == ("tmdb", "movie-603")
    assert media_ref("tvshow", {"tmdb": "1399", "tvdb": "121361"}) == ("tmdb", "series-1399")
    assert media_ref("movie", {"imdb": "tt0133093"}) == ("imdb", "tt0133093")
    assert media_ref("tvshow", {"tvdb": "121361"}) == ("tvdb", "121361")


def test_media_ref_ignores_junk_and_tvdb_for_movies():
    assert media_ref("movie", {"tvdb": "123"}) is None
    assert media_ref("movie", {"tmdb": "", "imdb": "unknown"}) is None
    assert media_ref("tvshow", {}) is None
    assert media_ref("tvshow", None) is None


def test_urls_match_the_jellyfin_plugin_formats():
    urls = UrlBuilder(BASE, "TP-key")
    assert urls.art("poster", ("tmdb", "movie-603")) == BASE + "/TP-key/tmdb/poster/movie-603.jpg"
    assert urls.art("poster", ("imdb", "tt0944947")) == BASE + "/TP-key/imdb/poster/tt0944947.jpg"
    assert urls.episode_thumb(("tmdb", "series-1399"), 2, 5) == BASE + "/TP-key/tmdb/thumbnail/series-1399/S2E5.jpg"


def test_other_art_types_and_season_suffix():
    urls = UrlBuilder(BASE + "/", "TP-key")
    ref = ("tmdb", "series-1399")
    assert urls.art("landscape", ref) == BASE + "/TP-key/tmdb/banner/series-1399.jpg"
    assert urls.art("fanart", ref) == BASE + "/TP-key/tmdb/background/series-1399.jpg"
    assert urls.art("clearlogo", ref) == BASE + "/TP-key/tmdb/logo/series-1399.png"
    assert urls.art("poster", ref, season=3) == BASE + "/TP-key/tmdb/poster/series-1399-s3.jpg"


def test_fallback_only_for_remote_originals():
    urls = UrlBuilder(BASE, "TP-key")
    original = "https://image.tmdb.org/t/p/original/abc.jpg"
    url = urls.art("poster", ("tmdb", "movie-603"), original)
    assert parse_qs(urlparse(url).query) == {"fallback_url": [original]}
    assert "?" not in urls.art("poster", ("tmdb", "movie-603"), "/media/Movies/Matrix/poster.jpg")
    assert "?" not in urls.art("poster", ("tmdb", "movie-603"), "smb://nas/poster.jpg")


def test_unwrap_roundtrips_kodi_encoding():
    url = BASE + "/TP-key/tmdb/poster/movie-603.jpg?fallback_url=https%3A%2F%2Fimage.tmdb.org%2Fa.jpg"
    assert unwrap(wrap(url)) == url
    assert unwrap("https://plain/x.jpg") == "https://plain/x.jpg"
    assert unwrap("") is None and unwrap(None) is None


def ours(url):
    return url.startswith(BASE + "/")


def make_ours(art_type, original):
    return BASE + "/k/%s.jpg?fb=%s" % (art_type, original)


def test_reconcile_replaces_and_remembers_originals():
    saved = {}
    changes = reconcile(("poster", "fanart"), {"poster": "https://tmdb/p.jpg"}, saved, make_ours, ours)
    assert changes == {"poster": BASE + "/k/poster.jpg?fb=https://tmdb/p.jpg",
                       "fanart": BASE + "/k/fanart.jpg?fb=None"}
    assert saved == {"poster": "https://tmdb/p.jpg"}


def test_reconcile_is_idempotent():
    saved = {"poster": "https://tmdb/p.jpg"}
    current = {"poster": BASE + "/k/poster.jpg?fb=https://tmdb/p.jpg"}
    assert reconcile(("poster",), current, saved, make_ours, ours) == {}


def test_reconcile_restores_original_or_removes():
    saved = {"poster": "https://tmdb/p.jpg"}
    current = {"poster": BASE + "/k/poster.jpg", "fanart": BASE + "/k/fanart.jpg"}
    changes = reconcile(("poster", "fanart"), current, saved, lambda *a: None, ours)
    assert changes == {"poster": "https://tmdb/p.jpg", "fanart": None}


def test_reconcile_takes_a_rescraped_original():
    saved = {"poster": "https://tmdb/old.jpg"}
    changes = reconcile(("poster",), {"poster": "https://tmdb/new.jpg"}, saved, make_ours, ours)
    assert saved == {"poster": "https://tmdb/new.jpg"}
    assert changes == {"poster": BASE + "/k/poster.jpg?fb=https://tmdb/new.jpg"}


def test_installation_id_is_added_next_to_the_fallback():
    urls = UrlBuilder(BASE, "TP-key", device_id="abc123")
    poster = urls.art("poster", ("tmdb", "movie-603"), "https://image.tmdb.org/t/p/w500/x.jpg?a=1&b=2")
    params = parse_qs(urlparse(poster).query)
    assert params == {"fallback_url": ["https://image.tmdb.org/t/p/w500/x.jpg?a=1&b=2"], "device_id": ["abc123"]}
    assert urls.episode_thumb(("tmdb", "series-1399"), 2, 5) == BASE + "/TP-key/tmdb/thumbnail/series-1399/S2E5.jpg?device_id=abc123"
