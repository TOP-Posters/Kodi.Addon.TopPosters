import json
from urllib.parse import parse_qs, urlparse

import pytest

from resources.lib.library import Library
from resources.lib.store import Store
from resources.lib.sync import Config, Syncer

from fakekodi import FakeKodi

BASE = "https://api.top-posters.com"
TMDB = "https://image.tmdb.org/t/p/original/"
ALL_ON = {"poster": True, "season_poster": True, "thumb": True,
          "landscape": True, "fanart": True, "clearlogo": True}


@pytest.fixture
def kodi():
    k = FakeKodi()
    k.add("movie", 1, {"poster": TMDB + "matrix.jpg", "fanart": TMDB + "matrix-bg.jpg"},
          title="The Matrix", uniqueid={"tmdb": "603", "imdb": "tt0133093"})
    k.add("movie", 2, {"poster": "/media/Movies/Home/poster.jpg"}, title="Home video", uniqueid={})
    k.add("movie", 3, {"poster": "smb://nas/Movies/Alien/poster.jpg"},
          title="Alien", uniqueid={"imdb": "tt0078748"})
    k.add("tvshow", 10, {"poster": TMDB + "got.jpg"}, title="Game of Thrones",
          uniqueid={"tmdb": "1399", "tvdb": "121361"})
    k.add("season", 100, {"poster": TMDB + "got-s1.jpg"}, tvshowid=10, season=1)
    k.add("season", 101, {}, tvshowid=10, season=0)
    k.add("episode", 1000, {"thumb": TMDB + "got-s1e1.jpg"}, tvshowid=10, season=1, episode=1)
    k.add("episode", 1001, {"thumb": TMDB + "got-s0e1.jpg"}, tvshowid=10, season=0, episode=1)
    return k


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "state.json"))


def run(kodi, store, **config):
    config.setdefault("api_key", "TP-key")
    syncer = Syncer(Library(kodi.rpc), Config(**config), store)
    return syncer.run_all(), syncer


def fallback(url):
    return parse_qs(urlparse(url).query).get("fallback_url", [None])[0]


def path(url):
    return urlparse(url).path


def test_posters_only_by_default_choice(kodi, store):
    changed, _ = run(kodi, store, toggles={"poster": True, "season_poster": True})
    assert changed == 3  # Matrix, GoT, GoT season 1; local art needs a prepared replacement
    matrix = kodi.art("movie", 1)
    assert path(matrix["poster"]) == "/TP-key/tmdb/poster/movie-603.jpg"
    assert fallback(matrix["poster"]) == TMDB + "matrix.jpg"
    assert matrix["fanart"] == TMDB + "matrix-bg.jpg"
    # No usable ID: left alone
    assert kodi.art("movie", 2) == {"poster": "/media/Movies/Home/poster.jpg"}
    # Without a local downloader, keep the original rather than an unsafe HTTP URL.
    assert kodi.art("movie", 3)["poster"] == "smb://nas/Movies/Alien/poster.jpg"
    assert path(kodi.art("tvshow", 10)["poster"]) == "/TP-key/tmdb/poster/series-1399.jpg"
    assert path(kodi.art("season", 100)["poster"]) == "/TP-key/tmdb/poster/series-1399-s1.jpg"
    # Specials are skipped
    assert kodi.art("season", 101) == {}
    assert kodi.art("episode", 1000)["thumb"] == TMDB + "got-s1e1.jpg"


def test_second_pass_writes_nothing(kodi, store):
    run(kodi, store, toggles=ALL_ON)
    writes_before = [c for c in kodi.calls if c[0].startswith("VideoLibrary.Set")]
    changed, syncer = run(kodi, Store(store.path), toggles=ALL_ON)
    assert changed == 0 and syncer.written == []
    assert [c for c in kodi.calls if c[0].startswith("VideoLibrary.Set")] == writes_before


def test_all_art_types(kodi, store):
    run(kodi, store, toggles=ALL_ON)
    matrix = kodi.art("movie", 1)
    assert path(matrix["landscape"]) == "/TP-key/tmdb/banner/movie-603.jpg"
    assert path(matrix["fanart"]) == "/TP-key/tmdb/background/movie-603.jpg"
    assert fallback(matrix["fanart"]) == TMDB + "matrix-bg.jpg"
    assert path(matrix["clearlogo"]) == "/TP-key/tmdb/logo/movie-603.png"
    assert path(kodi.art("episode", 1000)["thumb"]) == "/TP-key/tmdb/thumbnail/series-1399/S1E1.jpg"
    assert kodi.art("episode", 1001)["thumb"] == TMDB + "got-s0e1.jpg"


def test_plan_caps_keep_originals(kodi, store):
    run(kodi, store, toggles=ALL_ON, caps={"thumb": False, "landscape": False, "fanart": True})
    assert "landscape" not in kodi.art("movie", 1)
    assert kodi.art("episode", 1000)["thumb"] == TMDB + "got-s1e1.jpg"
    assert path(kodi.art("movie", 1)["fanart"]).endswith("/background/movie-603.jpg")


def test_turning_off_restores_exact_originals(kodi, store):
    originals = dict((k, dict((i, dict(it["art"])) for i, it in items.items())) for k, items in kodi.items.items())
    run(kodi, store, toggles=ALL_ON)
    changed, _ = run(kodi, Store(store.path), enabled=False, toggles=ALL_ON)
    assert changed > 0
    for kind, items in kodi.items.items():
        for dbid, item in items.items():
            assert item["art"] == originals[kind][dbid], (kind, dbid)


def test_switching_one_type_off_restores_only_that(kodi, store):
    run(kodi, store, toggles=ALL_ON)
    run(kodi, Store(store.path), toggles=dict(ALL_ON, fanart=False))
    matrix = kodi.art("movie", 1)
    assert matrix["fanart"] == TMDB + "matrix-bg.jpg"
    assert path(matrix["poster"]).endswith("/poster/movie-603.jpg")


def test_rescrape_is_picked_up_with_new_fallback(kodi, store):
    run(kodi, store, toggles={"poster": True})
    kodi.art("movie", 1)["poster"] = TMDB + "matrix-new.jpg"  # user refreshed the item
    syncer = Syncer(Library(kodi.rpc), Config(api_key="TP-key", toggles={"poster": True}), Store(store.path))
    assert syncer.run_item("movie", 1) == 1
    assert fallback(kodi.art("movie", 1)["poster"]) == TMDB + "matrix-new.jpg"
    run(kodi, Store(store.path), enabled=False)
    assert kodi.art("movie", 1)["poster"] == TMDB + "matrix-new.jpg"


def test_new_api_key_replaces_our_urls_and_keeps_originals(kodi, store):
    run(kodi, store, toggles={"poster": True})
    run(kodi, Store(store.path), api_key="TP-other", toggles={"poster": True})
    poster = kodi.art("movie", 1)["poster"]
    assert path(poster) == "/TP-other/tmdb/poster/movie-603.jpg"
    assert fallback(poster) == TMDB + "matrix.jpg"


def test_run_item_for_episode_and_season(kodi, store):
    syncer = Syncer(Library(kodi.rpc), Config(api_key="TP-key", toggles=ALL_ON), store)
    assert syncer.run_item("episode", 1000) == 1
    assert syncer.run_item("season", 100) == 1
    assert path(kodi.art("episode", 1000)["thumb"]).endswith("/series-1399/S1E1.jpg")
    assert kodi.art("movie", 1)["poster"] == TMDB + "matrix.jpg"


def test_store_drops_empty_records(kodi, store):
    run(kodi, store, toggles={"poster": True})
    with open(store.path) as f:
        data = json.load(f)
    assert data["originals"]["movie:1"] == {"poster": TMDB + "matrix.jpg", "fanart": TMDB + "matrix-bg.jpg"}
    assert "season:101" not in data["originals"]


def test_remove_textures_only_ours(kodi):
    ours = kodi.cache(BASE + "/TP-key/tmdb/poster/movie-603.jpg")
    theirs = kodi.cache(TMDB + "matrix.jpg")
    assert Library(kodi.rpc).remove_textures(BASE + "/") == 1
    assert ours not in kodi.textures and theirs in kodi.textures
